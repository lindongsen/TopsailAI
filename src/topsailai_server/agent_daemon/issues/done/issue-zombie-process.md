---
maintainer: AI
status: fixed
created: 2026-04-29
---

# Issue: agent_daemon 子进程产生僵尸进程（Zombie/Defunct）

## 问题描述

agent_daemon 主进程（PID 761947）创建的 `summarizer.sh` 子进程结束后未正常回收，变成僵尸进程（zombie/defunct）。

现象：
```
root@ai-dev:~# ps -ef | grep 761947
root      761947       1  0 Apr22 ?        00:19:04 python3 /root/ai/TopsailAI/src/topsailai_server/agent_daemon/topsailai_agent_daemon.py start
root      956403  761947  0 Apr23 ?        00:00:00 [summarizer.sh] <defunct>
root      956404  761947  0 Apr23 ?        00:00:00 [summarizer.sh] <defunct>
```

## 根因分析

1. **缺少 SIGCHLD 信号处理器**
   - `main.py` 中只注册了 `SIGTERM` 和 `SIGINT` 信号处理器，未注册 `SIGCHLD`。
   - 当子进程终止时，内核向父进程发送 `SIGCHLD` 信号；父进程若不处理，子进程状态无法被回收，变成僵尸进程。

2. **父进程未调用 wait/waitpid 回收子进程**
   - `WorkerManager.start_summarizer()` 通过 `subprocess.Popen` 创建子进程后，调用方立即返回，不等待子进程结束。
   - `WorkerManager` 仅在主进程退出时的 `stop_all()` 中清理，日常运行中不主动回收已终止的子进程。

3. **进程名显示为 `[summarizer.sh]` 的原因**
   - `summarizer.sh` 使用 `exec python3 ...` 启动，shell 进程被替换但原始条目仍留在进程表中。
   - python3 退出后，shell 原始条目需要父进程 `waitpid` 回收；未回收则显示为 `[summarizer.sh] <defunct>`。

## 修复方案

### 1. 核心修复：在 main.py 中添加 SIGCHLD 信号处理器

在 `main.py` 中新增 `sigchld_handler` 函数：

```python
def sigchld_handler(signum, frame):
    """Reap terminated child processes to prevent zombie processes."""
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
        except ChildProcessError:
            break
```

并在 `main()` 函数的信号注册处添加：
```python
signal.signal(signal.SIGCHLD, sigchld_handler)
```

### 2. 增强修复：WorkerManager 定期清理

在 `WorkerManager` 类中新增 `_reap_finished_processes` 方法：

```python
def _reap_finished_processes(self):
    """Remove finished processes from running_processes to free resources."""
    for session_id, process in list(self.running_processes.items()):
        if process.poll() is not None:
            del self.running_processes[session_id]
```

在 `start_summarizer()` 方法开头调用 `self._reap_finished_processes()`。

## 修改的文件列表

| 文件 | 修改内容 |
|------|----------|
| `main.py` | 新增 `sigchld_handler` 函数，注册 `SIGCHLD` 信号处理器 |
| `worker/process_manager.py` | 新增 `_reap_finished_processes()` 方法，在 `start_summarizer()` 中调用 |

## 验证

- `python3 -m py_compile main.py` ✅ 通过
- `python3 -m py_compile worker/process_manager.py` ✅ 通过

## 备注

- 需要重启 agent_daemon 服务才能使 `SIGCHLD` 处理器生效（信号处理器只在进程启动时注册）。
- 现有的僵尸进程在父进程重启前会一直存在，重启后新的 summarizer 子进程将正常被回收。
