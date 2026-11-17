---
maintainer: AI
author: DawsonLin
workspace: ..
ProjectFolder: ..
ProjectRootFolder: ../../..
ProjectCode: TOPSAILAI
programming_language: python
---

# input_bell 无声但脚本误判播放成功

## 现象

用户测试 `scripts/input_bell.py` 听不到声音。`python3 scripts/input_bell.py --test-sound`
返回 `EXIT=0` 并打印 `sound test passed: bell played`，但实际没有任何声音输出。

## 根因

ffplay 实际无法打开音频设备，但脚本的失败检测机制完全失效，误判为播放成功。

### 因果链

1. **环境**：容器环境，无 PulseAudio 进程（`_pulseaudio_sessions()` 返回空）；
   `/proc/asound` 为空目录（`/proc/asound/pcm` 不存在），`_alsa_playback_devices()`
   返回空。`_sound_candidates()` 只剩 1 个候选：普通 ffplay 命令（无额外环境变量）。

2. **ffplay 行为**：默认 ALSA 设备打开失败：
   - `SDL_OpenAudio (1 channels, 44100 Hz): ALSA: Couldn't open audio device: Device or resource busy`
   - `No more combinations to try, audio open failed`
   - 但 **ffplay 退出码为 0**（`-autoexit` 在 lavfi 输入结束时正常退出，不反映音频初始化失败）。

3. **脚本检测漏洞**（`_run_sound_command`）：
   - 使用 `-loglevel quiet` 运行 ffplay，抑制了 `audio open failed` 等关键错误，
     stderr 只剩 `ALSA lib pcm_dmix.c:1000:(snd_pcm_dmix_open) unable to open slave`。
   - 失败标记列表 `("couldn't open audio device", "audio open failed", "failed to open file")`
     匹配不到 `unable to open slave`。
   - `returncode == 0` 不触发失败分支。
   - 结论：`_run_sound_command()` 返回 `True`，`_ring_bell()` 缓存该候选并报告成功。

4. **结果**：`--test-sound` 返回 0，日志显示 `selected ffplay bell audio output`，
   但实际无声。

## 验证证据

- `ffplay -nodisp -autoexit -loglevel debug ...` 显示 `audio open failed`，但 `EXIT=0`。
- `ffplay -nodisp -autoexit -loglevel quiet ...` stderr 仅 `unable to open slave`，
  不匹配任何失败标记（Python 模拟确认 `script_would_report: False`）。
- 指定 `SDL_AUDIODRIVER=alsa AUDIODEV=plughw:0,0` 同样 `audio open failed`（debug 模式可见）。

## 修复建议

1. 失败标记补充 ALSA 错误模式：`"unable to open slave"`、`"device or resource busy"`、
   `"couldn't open audio device"`（大小写已 lower 处理）。
2. 不要用 `-loglevel quiet`，改用 `-loglevel error` 或 `-loglevel warning`，
   保留 ALSA 错误输出，使检测逻辑能看到真实错误。
3. ffplay 退出码不可靠（音频失败仍返回 0），应以 stderr 错误模式为主要判据。
4. 探测增强：`/proc/asound` 为空时，可回退扫描 `/dev/snd/pcmC*D*p` 设备节点
   （当前环境存在 `pcmC0D0p` 等），构造 `plughw:N,M` 候选。
