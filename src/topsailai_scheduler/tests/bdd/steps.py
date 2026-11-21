"""Step definitions for every BDD feature module.

All steps live here rather than beside each feature so a step is defined exactly
once. pytest-bdd rejects a duplicate definition, and duplicating a step per
feature is how two features silently drift apart.

Every step drives the real binary through the mock provider. Nothing inside the
scheduler is mocked, so a passing scenario is evidence about the shipped binary.
"""

import json
import os
import re
import shutil
import time

from pytest_bdd import given, step, then, when

from support import MOCK_PROVIDER, wait_for_pid_gone


def _remember(session, task):
    """Record the last CLI result so a later step can assert on it.

    The session's own last_output is overwritten by any intervening CLI call, so
    the result of the action under test is copied out immediately.
    """
    task.last = {
        "code": session.last_code,
        "out": session.last_output,
        "err": session.last_error,
    }


# --------------------------------------------------------------------- given


@given("a task that prints a line", target_fixture="task")
def a_task_that_prints_a_line(session, task):
    """Write a task that prints a marker line."""
    task.id = "data/work"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "echo work-ran"]\n',
        "# Work task\n\nPrints a marker line.\n",
    )
    return task


@given("a task that exits with status 3", target_fixture="task")
def a_task_that_exits_non_zero(session, task):
    """Write a task whose run exits with a non-zero status."""
    task.id = "data/failing"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "echo failing; exit 3"]\n',
        "# Failing task\n\nExits with status 3.\n",
    )
    return task


@given("a task that reads an environment variable it defines", target_fixture="task")
def a_task_that_reads_an_environment_variable(session, task):
    """Write a task whose run prints a variable the task defines."""
    task.id = "data/env"
    marker = os.path.join(session.workspace, "env.txt")
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "printf \'%%s\' \\"$BDD_VALUE\\" > %s"]\n'
        'env:\n  BDD_VALUE: "carried"\n' % marker,
        "# Environment task\n\nReads a variable it defines.\n",
    )
    return task


@given("a task that records its working directory", target_fixture="task")
def a_task_that_records_its_working_directory(session, task):
    """Write a task that names a workspace and records where it ran."""
    task.id = "data/pwd"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "pwd > {task_dir}/pwd.txt"]\n'
        'workspace: %s\n' % session.workspace,
        "# Working directory task\n\nRecords where it ran.\n",
    )
    return task


@given("a task that sleeps longer than the test", target_fixture="task")
def a_task_that_sleeps(session, task):
    """Write a task that outlives the scenario."""
    task.id = "slow/locked"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "sleep 30"]\n',
        "# Locked task\n\nSleeps so a second launch overlaps.\n",
    )
    return task


@given("a task that sleeps far longer than its timeout", target_fixture="task")
def a_task_that_outlives_its_timeout(session, task):
    """Write a task whose timeout is far shorter than its sleep."""
    task.id = "slow/timeout"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "sleep 120"]\ntimeout: 2s\n',
        "# Timeout task\n\nSleeps far longer than its timeout.\n",
    )
    return task


@given("a task nested two folders deep", target_fixture="task")
def a_nested_task(session, task):
    """Write a task two folders below the tasks root."""
    task.id = "daily/nightly/report"
    session.write_task(
        task.id,
        'schedule: "0 3 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "true"]\n',
        "# Report task\n\nProves nesting depth is unlimited.\n",
    )
    return task


@given("a task whose Markdown file is missing", target_fixture="task")
def a_task_without_content(session, task):
    """Write a task YAML with no Markdown file beside it."""
    task.id = "broken/nocontent"
    session.write_yaml_only(task.id, 'schedule: "0 8 * * *"\n')
    return task


@given("a task whose Markdown content is empty", target_fixture="task")
def a_task_with_empty_content(session, task):
    """Write a task whose content file exists but holds nothing."""
    task.id = "broken/empty"
    session.write_task(task.id, 'schedule: "0 8 * * *"\n', "")
    return task


@given("a task whose Markdown content is too short", target_fixture="task")
def a_task_with_short_content(session, task):
    """Write a task whose content is a few characters, below the minimum."""
    task.id = "broken/short"
    session.write_task(task.id, 'schedule: "0 8 * * *"\n', "short")
    return task


@given("a disabled task", target_fixture="task")
def a_disabled_task(session, task):
    """Write a task that is disabled in its own YAML."""
    task.id = "off/disabled"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nenabled: false\nlauncher: command\n'
        'command: /bin/sh\nargs: ["-c", "echo should-not-run"]\n',
        "# Disabled task\n\nMust never be launched.\n",
    )
    return task


@given("a task whose YAML names an unknown key", target_fixture="task")
def a_task_with_an_unknown_key(session, task):
    """Write a task whose YAML has a misspelled key."""
    task.id = "broken/typo"
    session.write_task(
        task.id,
        'schedul: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "true"]\n',
        "# Typo task\n\nA misspelled key must be rejected, not ignored.\n",
    )
    return task


@given("a task whose YAML names no schedule", target_fixture="task")
def a_task_without_a_schedule(session, task):
    """Write a task whose YAML omits the required schedule."""
    task.id = "broken/noschedule"
    session.write_task(
        task.id,
        'launcher: command\ncommand: /bin/sh\nargs: ["-c", "true"]\n',
        "# Unscheduled task\n\nOmits the required schedule.\n",
    )
    return task


@given("a task written after the scheduler started", target_fixture="task")
def a_task_written_after_startup(session, task):
    """Write a task while the daemon is already running."""
    task.id = "late/added"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "true"]\n',
        "# Late task\n\nAppears after the daemon started.\n",
    )
    return task


@given("a task that names its workspace timeout and environment", target_fixture="task")
def a_fully_configured_task(session, task):
    """Write a task that names every optional field."""
    task.id = "data/full"
    session.write_task(
        task.id,
        f'schedule: "0 8 * * *"\nlauncher: command\nprovider: {MOCK_PROVIDER}\n'
        'command: /bin/sh\nargs: ["-c", "true"]\n'
        'workspace: /tmp\ntimeout: 45s\n'
        'env:\n  BDD_ALPHA: "one"\n  BDD_BETA: "two"\n',
        "# Full task\n\nNames every optional field.\n",
    )
    return task


@given("a task that names no optional field", target_fixture="task")
def a_default_task(session, task):
    """Write a task that relies on every default."""
    task.id = "defaults/plain"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "true"]\n',
        "# Plain task\n\nRelies on every default.\n",
    )
    return task


@given("a task whose arguments carry every placeholder", target_fixture="task")
def a_task_with_every_placeholder(session, task):
    """Write a task whose arguments carry all five placeholders."""
    task.id = "placeholders/all"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "true", "{task}", "{task_id}", "{task_dir}", "{stem}", "{workspace}"]\n',
        "# Placeholder task\n\nCarries every placeholder.\n",
    )
    return task


@given("a task whose argument embeds a placeholder in a longer string", target_fixture="task")
def a_task_with_an_embedded_placeholder(session, task):
    """Write a task whose argument embeds a placeholder inside other text."""
    task.id = "placeholders/embedded"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "true", "prefix-{stem}-suffix"]\n',
        "# Embedded placeholder task\n\nEmbeds a placeholder in a longer argument.\n",
    )
    return task


@given("a task that names the mock provider explicitly", target_fixture="task")
def a_task_naming_the_mock_provider(session, task):
    """Write a task that selects the mock provider by path."""
    task.id = "provider/explicit"
    session.write_task(
        task.id,
        f'schedule: "0 8 * * *"\nlauncher: command\nprovider: {MOCK_PROVIDER}\n'
        'command: /bin/sh\nargs: ["-c", "true"]\n',
        "# Explicit provider task\n\nNames the provider instead of defaulting.\n",
    )
    return task


@given("a task that names an unknown provider", target_fixture="task")
def a_task_naming_an_unknown_provider(session, task):
    """Write a task that selects a provider executable that does not exist."""
    task.id = "provider/unknown"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\n'
        'provider: /nonexistent/absent-provider\n'
        'command: /bin/sh\nargs: ["-c", "true"]\n',
        "# Unknown provider task\n\nNames a provider that does not exist.\n",
    )
    return task


@given("a task whose provider appears later", target_fixture="task")
def a_task_whose_provider_appears_later(session, task):
    """Write a task naming a provider path that does not exist yet."""
    task.id = "provider/late"
    task.provider_path = os.path.join(session.workspace, "late-provider")
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\n'
        'provider: %s\n' % task.provider_path
        + 'command: /bin/sh\nargs: ["-c", "true"]\n',
        "# Late provider task\n\nNames a provider installed after startup.\n",
    )
    return task


@then("that task has no next run")
def no_next_run(session, task):
    """A rejected task must not be scheduled, so it has no next run.

    A zero next run is how the snapshot reports "not scheduled", so the zero
    value is the evidence that the cron never accepted the task.
    """
    status = session.task_status(task.id)
    assert status is not None, "task %r is missing from the status" % task.id
    assert status.get("next_run") in (None, "", "0001-01-01T00:00:00Z"), status


@when("the provider executable is installed")
def provider_executable_installed(session, task):
    """Install the provider the task names."""
    os.makedirs(os.path.dirname(task.provider_path), exist_ok=True)
    shutil.copyfile(MOCK_PROVIDER, task.provider_path)
    os.chmod(task.provider_path, 0o755)


@given("a task that outlives a killed supervisor", target_fixture="task")
def a_task_that_outlives_a_killed_supervisor(session, task):
    """Write a task that is still working when the daemon is killed."""
    task.id = "slow/reconcile"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "sleep 30"]\n',
        "# Reconcile task\n\nOutlives a killed supervisor.\n",
    )
    return task


@given("a task that finishes soon after its supervisor dies", target_fixture="task")
def a_task_that_finishes_soon(session, task):
    """Write a task that ends on its own shortly after the daemon is killed."""
    task.id = "slow/finish"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "sleep 3"]\n',
        "# Finishing task\n\nEnds on its own after the supervisor dies.\n",
    )
    return task


# ---------------------------------------------------------------------- when


@when("I launch that task and wait for it")
def launch_and_wait(session, task):
    """Launch the task and wait for the run to finish."""
    session.wait_for_discovery(task.id)
    session.cli("launch", task.id, "--wait")
    _remember(session, task)


@when("I launch that task and wait for it again")
def launch_and_wait_again(session, task):
    """Launch the same task a second time and wait for the run to finish."""
    session.cli("launch", task.id, "--wait")
    _remember(session, task)


@when("I launch that task without waiting")
def launch_without_waiting(session, task):
    """Launch the task and return as soon as it started."""
    session.wait_for_discovery(task.id)
    session.cli("launch", task.id)
    _remember(session, task)
    session.wait_for_request(task.id)


@when("I launch that task again without waiting")
def launch_again(session, task):
    """Launch the same task a second time while the first is running."""
    session.cli("launch", task.id)
    _remember(session, task)


@when("I launch that task again")
def launch_again_plain(session, task):
    """Launch the same task again after a restart."""
    session.cli("launch", task.id)
    _remember(session, task)


@when("I launch that task")
def launch_plain(session, task):
    """Launch the task without waiting, for a launch expected to be refused."""
    session.wait_for_discovery(task.id)
    session.cli("launch", task.id)
    _remember(session, task)


@when("I launch that task as JSON and wait for it")
def launch_as_json(session, task):
    """Launch the task and read the result as JSON."""
    session.wait_for_discovery(task.id)
    session.cli("launch", task.id, "--wait", "--json")
    _remember(session, task)


@step("I stop that task")
def stop_task(session, task):
    """Stop the task.

    The step is registered for every keyword because a scenario may use it as
    the action under test or as the cleanup of a run it started. The task is
    waited for first: a stop issued before the rescan would be refused as an
    unknown task rather than as a task that is not running.
    """
    session.wait_for_discovery(task.id)
    session.cli("stop", task.id)
    _remember(session, task)


@when("I kill the scheduler")
def kill_the_scheduler(session, task):
    """Kill the daemon without letting it clean up."""
    task.recorded = session.read_lock_record(task.id)
    session.kill_daemon()


@when("I restart the scheduler")
def restart_the_scheduler(session):
    """Start a fresh daemon in the same workspace."""
    session.restart_daemon()


@when("the recorded run finishes on its own")
def the_recorded_run_finishes(session, task):
    """Wait until the run left behind by the killed supervisor ends."""
    run_id = task.recorded.get("run_id")
    assert run_id, "the lock record named no run"
    session.wait_for_run_exit(run_id)


@when("the scheduler rescans the task tree")
def rescan(session, task):
    """Wait for the periodic rescan to report the task."""
    session.wait_for_discovery(task.id)


@when("I remove that task")
def remove_task(session, task):
    """Delete the task's files while the daemon is running."""
    session.remove_task(task.id)


@when("I ask for the status as JSON")
def status_as_json(session, task):
    """Read the status snapshot as JSON."""
    session.wait_for_discovery(task.id)
    session.cli("status", "--json")
    _remember(session, task)


@when("I ask for the status as a table")
def status_as_table(session, task):
    """Read the status snapshot as a table."""
    session.wait_for_discovery(task.id)
    session.cli("status")
    _remember(session, task)


@when("I launch a task that does not exist")
def launch_unknown_task(session, task):
    """Launch a task id that was never written."""
    session.cli("launch", "nope/missing")
    _remember(session, task)


@when("I launch with no task id")
def launch_without_an_id(session, task):
    """Call launch with no positional argument."""
    session.cli("launch")
    _remember(session, task)


@when("I run an unknown subcommand")
def run_unknown_subcommand(session, task):
    """Call the CLI with a subcommand it does not implement."""
    session.cli("nonsense")
    _remember(session, task)


@when("I ask for help")
def ask_for_help(session, task):
    """Ask the CLI for its usage text."""
    session.cli("help")
    _remember(session, task)


# ---------------------------------------------------------------------- then


@then("the launch reports exit code 0")
def launch_reports_zero(session, task):
    """The launch must report a zero exit code."""
    assert "exit code: 0" in task.last["out"], task.last["out"]


@then("the launch reports exit code 3")
def launch_reports_three(session, task):
    """The launch must report the exit status the run produced."""
    assert "exit code: 3" in task.last["out"], task.last["out"]


@then("the launch exits non-zero")
def launch_exits_non_zero(session, task):
    """A non-zero run status must make the CLI exit non-zero."""
    assert task.last["code"] != 0, "the CLI exited 0 for a run that exited 3"


@then("the run's output is captured")
def output_is_captured(session, task):
    """The provider must have captured the run's own output."""
    run_ids = session.run_ids_for(task.id)
    assert run_ids, "the provider recorded no run"
    captured = session.output_for_run(run_ids[-1])
    assert "work-ran" in captured, captured


@then("the run sees the value the task defined")
def run_sees_the_value(session, task):
    """The run must observe the variable the task defined."""
    marker = os.path.join(session.workspace, "env.txt")
    deadline = time.time() + 20
    while time.time() < deadline:
        if os.path.exists(marker) and os.path.getsize(marker) > 0:
            break
        time.sleep(0.1)
    assert os.path.exists(marker), "the run wrote no marker"
    with open(marker, "r", encoding="utf-8") as handle:
        assert handle.read() == "carried"


@then("the run recorded the workspace the task named")
def run_recorded_the_workspace(session, task):
    """The run must have executed in the workspace the task named."""
    marker = os.path.join(session.tasks_root, task.id + ".md")
    folder = os.path.dirname(marker)
    path = os.path.join(folder, "pwd.txt")
    deadline = time.time() + 20
    while time.time() < deadline:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            break
        time.sleep(0.1)
    assert os.path.exists(path), "the run recorded no working directory"
    with open(path, "r", encoding="utf-8") as handle:
        assert handle.read().strip() == session.workspace


@then("the launch reports a timeout")
def launch_reports_timeout(session, task):
    """The launch must report that the run timed out."""
    assert "timed out: yes" in task.last["out"], task.last["out"]


@then("the timeout is logged")
def timeout_logged(session):
    """The timeout must be visible in the daemon log."""
    assert session.wait_for_log("run timed out"), session.read_log()


@then("the stop is reported as supervised")
def stop_is_supervised(session, task):
    """A stop of a supervised run must not claim to be best effort."""
    assert "stop requested" in task.last["out"], task.last["out"]
    assert "best effort" not in task.last["out"], task.last["out"]


@then("the stop is reported as best effort")
def stop_is_best_effort(session, task):
    """A stop of an unsupervised run must say it cannot be confirmed."""
    assert "best effort" in task.last["out"], task.last["out"]


@then("the stop is refused as not running")
def stop_refused(session, task):
    """A stop with nothing to stop must be refused."""
    assert task.last["code"] != 0, "the stop was accepted with nothing running"
    assert "not running" in task.last["err"], task.last["err"]


@then("the run ends")
def the_run_ends(session, task):
    """The task must return to idle once the run is over."""
    session.wait_for_state(task.id, "idle")


@then("the run is recorded as stopped")
def the_run_is_recorded_as_stopped(session, task):
    """The completed run must be recorded as stopped."""
    status = session.wait_for_state(task.id, "idle")
    last = status.get("last_run") or {}
    assert last.get("stopped") is True, last


@then("the second launch is skipped as already running")
def second_launch_skipped(session, task):
    """The second launch must report the task as already running."""
    assert "already running" in task.last["out"], task.last["out"]


@then("the provider received exactly one request for that task")
def one_request(session, task):
    """A skipped launch must not reach the provider at all."""
    documents = session.requests_for(task.id)
    assert len(documents) == 1, "the provider received %d requests" % len(documents)


@then("the provider received two requests for that task")
def two_requests(session, task):
    """A second run must reach the provider exactly once more."""
    documents = session.requests_for(task.id)
    assert len(documents) == 2, "the provider received %d requests" % len(documents)


@then("that task is reported as invalid")
def reported_invalid(session, task):
    """The broken task must be reported as invalid."""
    status = session.wait_for_state(task.id, "invalid")
    assert status.get("error"), "an invalid task must carry its reason"


@then("the reason names the character count")
def reason_names_count(session, task):
    """The rejection reason must state how short the content is."""
    status = session.wait_for_state(task.id, "invalid")
    reason = status.get("error") or ""
    assert "characters" in reason, "the reason should name the character count: %r" % reason
    # The floor is configurable, so the reason must name a minimum without the
    # test pinning the number a deployment happens to use.
    assert re.search(r"at least \d+ are required", reason), (
        "the reason should name the minimum: %r" % reason
    )


@then("that task is reported as disabled")
def reported_disabled(session, task):
    """The disabled task must be reported as disabled."""
    session.wait_for_state(task.id, "disabled")


@then("that task is never launched")
def never_launched(session, task):
    """A task that cannot run must never reach the provider."""
    assert not session.requests_for(task.id), "a task that cannot run was launched"


@then("that task is discovered without a restart")
def discovered_without_restart(session, task):
    """A task written after startup must appear after the next rescan."""
    session.wait_for_discovery(task.id)


@then("that task is no longer reported")
def no_longer_reported(session, task):
    """A removed task must disappear after the next rescan."""
    session.wait_for_absent(task.id)


@then("the launch is refused as disabled")
def launch_refused_disabled(session, task):
    """A disabled task must be refused rather than run."""
    assert task.last["code"] != 0, "a disabled task was launched"
    assert "disabled" in task.last["err"], task.last["err"]


@then("the launch is refused because the provider is unknown")
def launch_refused_unknown_provider(session, task):
    """A task naming a missing provider must be refused with its location."""
    assert task.last["code"] != 0, "a task with an unknown provider was launched"
    assert "does not exist" in task.last["err"], task.last["err"]
    assert "/nonexistent/absent-provider" in task.last["err"], task.last["err"]


@then("the launch is refused as not found")
def launch_refused_not_found(session, task):
    """An unknown task id must be refused."""
    assert task.last["code"] != 0, "an unknown task was launched"
    assert "not found" in task.last["err"], task.last["err"]


@then("the provider received the relative task id")
def relative_task_id(session, task):
    """The provider must receive the relative id, not an absolute path."""
    assert session.request_for(task.id)["task_id"] == task.id


@then("the provider received the task's own folder")
def task_folder(session, task):
    """The provider must receive the folder holding the task files."""
    expected = os.path.dirname(os.path.join(session.tasks_root, task.id))
    assert session.request_for(task.id)["task_dir"] == expected


@then("the provider received the workspace the task named")
def workspace_named(session, task):
    """An explicit workspace must be sent unchanged."""
    assert session.request_for(task.id)["workspace"] == "/tmp"


@then("the provider received the timeout the task named")
def timeout_named(session, task):
    """An explicit timeout must be sent in milliseconds."""
    assert session.request_for(task.id)["timeout_ms"] == 45000


@then("the provider received the environment the task named")
def environment_named(session, task):
    """The task's environment must be sent unchanged."""
    assert session.request_for(task.id)["env"] == {"BDD_ALPHA": "one", "BDD_BETA": "two"}


@then("the provider received the command the task named")
def command_named(session, task):
    """The command the task named must be sent unchanged."""
    assert session.request_for(task.id)["command"] == "/bin/sh"


@then("the provider received the default workspace")
def default_workspace(session, task):
    """A task without a workspace must receive the scheduler default."""
    assert session.request_for(task.id)["workspace"] == session.workspace


@then("the provider received the default timeout")
def default_timeout(session, task):
    """A task without a timeout must receive the scheduler default."""
    assert session.request_for(task.id)["timeout_ms"] == 30000


@then("the provider received no environment")
def no_environment(session, task):
    """A task without environment variables must send none.

    The field is present and null rather than omitted, so a provider can tell
    "the task set nothing" from "the scheduler forgot to send the field".
    """
    document = session.request_for(task.id)
    assert "env" in document, "the env field was omitted entirely"
    assert document["env"] is None, document["env"]


@then("the provider received every placeholder expanded")
def every_placeholder_expanded(session, task):
    """Every placeholder must be replaced by the value it stands for."""
    document = session.request_for(task.id)
    folder = os.path.dirname(os.path.join(session.tasks_root, task.id))
    expected = [
        "-c",
        "true",
        os.path.join(session.tasks_root, task.id + ".md"),
        task.id,
        folder,
        os.path.basename(task.id),
        session.workspace,
    ]
    assert document["args"] == expected, document["args"]


@then("the embedded placeholder is expanded in place")
def embedded_placeholder_expanded(session, task):
    """A placeholder inside a longer argument must be replaced, not dropped.

    The task id is placeholders/embedded, so {stem} is "embedded". The whole
    argument must survive around the substitution: a naive implementation that
    replaces the argument instead of the placeholder would lose the prefix and
    the suffix.
    """
    document = session.request_for(task.id)
    assert document["args"][2] == "prefix-embedded-suffix", document["args"]


@then("the provider received the current protocol version")
def protocol_version(session, task):
    """The request must carry the protocol revision the provider speaks."""
    assert session.request_for(task.id)["protocol_version"] == 1


@then("the provider received the request")
def provider_received_request(session, task):
    """The named provider must have received the request."""
    document = session.request_for(task.id)
    assert document["task_id"] == task.id


@then("the lock file carries a record naming the run")
def lock_record_names_the_run(session, task):
    """The supervisor must record the run it is supervising."""
    record = session.wait_for_lock_record(task.id)
    assert record["run_id"], record


@then("the record names the provider that owns the run")
def record_names_the_provider(session, task):
    """The record must name the provider, so a restart asks the right one."""
    assert session.read_lock_record(task.id)["provider"] == MOCK_PROVIDER


@then("the record names the supervisor that wrote it")
def record_names_the_supervisor(session, task):
    """The record must name the process that wrote it."""
    record = session.read_lock_record(task.id)
    assert record["scheduler_pid"] == session.daemon_pid(), record


@then("the lock record is empty")
def lock_record_is_empty(session, task):
    """A confirmed-finished run must leave no record behind."""
    deadline = time.time() + 20
    while time.time() < deadline:
        if not session.read_lock_record(task.id):
            return
        time.sleep(0.1)
    raise AssertionError("the lock record was not cleared: %r"
                         % session.read_lock_record(task.id))


@then("the skip is logged as a reconciliation")
def skip_logged_as_reconciliation(session):
    """A skip caused by a previous supervisor must not read as a lock conflict."""
    assert session.wait_for_log("a run from a previous supervisor is still in flight"), \
        session.read_log()


@then("the lock record still names the run")
def record_still_names_the_run(session, task):
    """The record must outlive the supervisor that wrote it."""
    record = session.read_lock_record(task.id)
    assert record.get("run_id") == task.recorded.get("run_id"), record


@then("the launch starts a new run")
def launch_starts_a_new_run(session, task):
    """A recorded run that already finished must not block the task."""
    assert "started" in task.last["out"], task.last["out"]


@then("the recorded run ends")
def recorded_run_ends(session, task):
    """A forwarded stop must actually end the run it named."""
    pid = task.recorded.get("pid")
    assert pid, "the lock record named no pid"
    wait_for_pid_gone(pid)


@then("the snapshot names the task")
def snapshot_names_the_task(session, task):
    """The snapshot must list the discovered task."""
    document = json.loads(task.last["out"])
    ids = [entry.get("id") for entry in document.get("tasks") or []]
    assert task.id in ids, ids


@then("the snapshot reports the tasks root")
def snapshot_reports_the_root(session, task):
    """The snapshot must report the folder it scanned."""
    document = json.loads(task.last["out"])
    assert document.get("tasks_root") == session.tasks_root, document.get("tasks_root")


@then("the snapshot reports the task as idle")
def snapshot_reports_idle(session, task):
    """A task with no in-flight run must be reported idle."""
    document = json.loads(task.last["out"])
    for entry in document.get("tasks") or []:
        if entry.get("id") == task.id:
            assert entry.get("state") == "idle", entry
            return
    raise AssertionError("task %r was not in the snapshot" % task.id)


@then("the table names the task")
def table_names_the_task(session, task):
    """The human-readable table must list the task."""
    assert task.id in task.last["out"], task.last["out"]


@then("the launch reports the task id and a pid")
def launch_reports_pid(session, task):
    """A launch must report the identity of the run it started."""
    assert "task %s started" % task.id in task.last["out"], task.last["out"]
    assert "pid" in task.last["out"], task.last["out"]


@then("the command line is rejected as a usage error")
def usage_error(session, task):
    """A wrong command line must be reported as a usage error, not a failure."""
    assert task.last["code"] == 2, "want exit 2, got %d" % task.last["code"]


@then("the help text names every subcommand")
def help_names_subcommands(session, task):
    """The usage text must document every subcommand."""
    for name in ("run", "status", "launch", "stop"):
        assert name in task.last["out"], "the help text omits %r" % name


@then("the JSON result names the task and its exit code")
def json_result(session, task):
    """A JSON launch result must carry the task id and the run's exit status."""
    document = json.loads(task.last["out"])
    assert document.get("task_id") == task.id, document
    record = document.get("record") or {}
    assert record.get("exit_code") == 0, record


# ------------------------------------------------- cron scheduling (given)


@given("a task scheduled every two seconds", target_fixture="task")
def a_task_scheduled_every_two_seconds(session, task):
    """Write a task whose cron fires every two seconds.

    Nothing in the scenario calls launch, so a request reaching the provider can
    only come from the cron. That is what makes this evidence about scheduling
    rather than about the launch path.
    """
    task.id = "cron/tick"
    session.write_task(
        task.id,
        'schedule: "*/2 * * * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "echo tick"]\n',
        "# Tick task\n\nFires on its own schedule.\n",
    )
    return task


@given("a task with a five-field schedule", target_fixture="task")
def a_task_with_a_five_field_schedule(session, task):
    """Write a task using the familiar five-field cron form."""
    task.id = "cron/five"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "true"]\n',
        "# Five field task\n\nUses the familiar cron form.\n",
    )
    return task


@given("a task whose schedule cannot be parsed", target_fixture="task")
def a_task_with_a_broken_schedule(session, task):
    """Write a task whose schedule is not a cron expression."""
    task.id = "cron/broken"
    session.write_task(
        task.id,
        'schedule: "not a cron"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "true"]\n',
        "# Broken schedule task\n\nMust be reported, never fired.\n",
    )
    return task


# ------------------------------------------- concurrency and shutdown (given)


@given("a scheduler that allows one run at a time", target_fixture="task")
def a_scheduler_with_one_slot(session, task):
    """Restart the daemon with a single concurrency slot.

    The limit is read once at startup and cannot be expressed in a task file, so
    the daemon is restarted with it before any task is written.
    """
    session.reconfigure({"SCHEDULER_MAX_CONCURRENT": "1"})
    return task


@given("a scheduler with a generous shutdown grace", target_fixture="task")
def a_scheduler_with_a_generous_grace(session, task):
    """Restart the daemon with a grace period longer than the run."""
    session.reconfigure({"SCHEDULER_SHUTDOWN_GRACE": "10s"})
    return task


@given("a scheduler with a short shutdown grace", target_fixture="task")
def a_scheduler_with_a_short_grace(session, task):
    """Restart the daemon with a grace period far shorter than the run."""
    session.reconfigure({"SCHEDULER_SHUTDOWN_GRACE": "1s"})
    return task


@given("two tasks that each sleep for a while", target_fixture="task")
def two_sleeping_tasks(session, task):
    """Write two tasks that each hold a slot for several seconds."""
    task.id = "slots/first"
    task.second = "slots/second"
    for task_id in (task.id, task.second):
        session.write_task(
            task_id,
            'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
            'args: ["-c", "sleep 4"]\n',
            "# Slot task\n\nHolds a concurrency slot.\n",
        )
    return task


@given("a task that sleeps for a while", target_fixture="task")
def a_task_that_sleeps_for_a_while(session, task):
    """Write a task that is still working when the daemon is asked to stop."""
    task.id = "shutdown/drain"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "sleep 6"]\n',
        "# Drain task\n\nOutlives the shutdown request.\n",
    )
    return task


@given("a task that sleeps far longer than the grace period", target_fixture="task")
def a_task_that_outlives_the_grace(session, task):
    """Write a task that cannot finish inside the grace period."""
    task.id = "shutdown/cancel"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "sleep 30"]\n',
        "# Cancel task\n\nCannot finish inside the grace period.\n",
    )
    return task


# ------------------------------------------------- launcher selection (given)


@given("a task that names no launcher", target_fixture="task")
def a_task_without_a_launcher(session, task):
    """Write a task that leaves the invocation to the provider."""
    task.id = "launcher/agent"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\n',
        "# Agent task\n\nLeaves the invocation to the provider.\n",
    )
    return task


@given("a task that names an unknown launcher", target_fixture="task")
def a_task_with_an_unknown_launcher(session, task):
    """Write a task that selects a launcher that does not exist."""
    task.id = "launcher/unknown"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: nope\ncommand: /bin/sh\n'
        'args: ["-c", "true"]\n',
        "# Unknown launcher task\n\nNames a launcher that does not exist.\n",
    )
    return task


@given("a task that names the command launcher", target_fixture="task")
def a_task_with_the_command_launcher(session, task):
    """Write a task that names its own command and arguments."""
    task.id = "launcher/command"
    session.write_task(
        task.id,
        'schedule: "0 8 * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "echo named"]\n',
        "# Command task\n\nNames its own command.\n",
    )
    return task


# ------------------------------------------------- cron scheduling (when/then)


@when("I wait for the schedule to fire")
def wait_for_the_schedule_to_fire(session, task):
    """Wait until the cron has produced a run without anyone calling launch."""
    session.wait_for_discovery(task.id)
    session.wait_for_request_count(task.id, 1, timeout=30)


@when("I change its schedule to every second")
def change_the_schedule(session, task):
    """Rewrite the task YAML with a faster schedule."""
    task.baseline = len(session.run_ids_for(task.id))
    session.write_task(
        task.id,
        'schedule: "* * * * * *"\nlauncher: command\ncommand: /bin/sh\n'
        'args: ["-c", "echo tick"]\n',
        "# Tick task\n\nFires on its own schedule.\n",
    )


@then("the provider received at least one request for that task")
def at_least_one_request(session, task):
    """A cron-fired run must reach the provider."""
    documents = session.requests_for(task.id)
    assert documents, "the cron fired no run"


@then("the task is logged as scheduled")
def logged_as_scheduled(session, task):
    """The daemon must report the task as registered with the cron."""
    assert session.wait_for_log("task scheduled"), session.read_log()


@then("that task is scheduled with a next run")
def scheduled_with_a_next_run(session, task):
    """A five-field expression must be accepted and given a next run.

    A zero next run is how the snapshot reports "not scheduled", so a non-zero
    value is the only evidence that the cron accepted the expression.
    """
    status = session.wait_for_discovery(task.id)
    deadline = time.time() + 20
    while time.time() < deadline:
        status = session.task_status(task.id)
        if status and status.get("next_run") not in (None, "", "0001-01-01T00:00:00Z"):
            return
        time.sleep(0.1)
    raise AssertionError("task %r was never given a next run: %r" % (task.id, status))


@then("that task is reported as idle with no next run")
def idle_without_a_next_run(session, task):
    """A task whose schedule cannot be parsed must not be scheduled."""
    status = session.wait_for_state(task.id, "idle")
    assert status.get("next_run") in (None, "", "0001-01-01T00:00:00Z"), status


@then("that task is reported as idle")
def idle_with_a_next_run(session, task):
    """A task whose provider became usable must be scheduled and idle."""
    status = session.wait_for_state(task.id, "idle")
    assert not status.get("error"), status.get("error")


@then("the schedule failure is logged")
def schedule_failure_logged(session):
    """The rejected schedule must be reported with its reason."""
    assert session.wait_for_log("task not scheduled"), session.read_log()
    assert "invalid schedule" in session.read_log(), session.read_log()


@then("the task is rescheduled without a restart")
def rescheduled_without_a_restart(session, task):
    """A changed schedule must be picked up by the periodic rescan."""
    assert session.wait_for_log("task changed, rescheduling"), session.read_log()


@then("the provider receives more requests than before")
def more_requests_than_before(session, task):
    """The faster schedule must produce runs the old one would not have."""
    current = session.wait_for_request_growth(task.id, task.baseline, timeout=30)
    assert current > task.baseline, (current, task.baseline)


# ------------------------------------------- concurrency and shutdown (when)


@when("I launch the first task without waiting")
def launch_the_first_task(session, task):
    """Start the first task so it occupies the only slot."""
    session.wait_for_discovery(task.id)
    session.cli("launch", task.id)
    _remember(session, task)
    session.wait_for_request(task.id)


@when("I launch the second task and time it")
def launch_the_second_task_timed(session, task):
    """Start the second task and measure how long the launch call took.

    The launch blocks until a slot frees, so the duration is the observable
    evidence that the limit was applied. A launch that ignored the limit would
    return immediately.
    """
    session.wait_for_discovery(task.second)
    started = time.time()
    session.cli("launch", task.second)
    task.elapsed = time.time() - started
    _remember(session, task)


@when("I stop the scheduler gracefully")
def stop_the_scheduler_gracefully(session, task):
    """Send SIGTERM and measure how long the daemon took to exit."""
    task.elapsed = session.terminate_daemon()


@then("the second launch waited for the first run")
def second_launch_waited(session, task):
    """The second launch must have blocked until the first run released a slot."""
    assert task.elapsed >= 2.0, "the second launch returned in %.2fs" % task.elapsed


@then("the provider received a request for each task")
def a_request_for_each_task(session, task):
    """Waiting for a slot must end in a run, not in a silent drop."""
    for task_id in (task.id, task.second):
        assert session.requests_for(task_id), "no request for %r" % task_id


@then("the shutdown waited for the run")
def shutdown_waited(session, task):
    """A drain must wait for the run instead of abandoning it."""
    assert task.elapsed >= 3.0, "the daemon exited in %.2fs" % task.elapsed
    assert session.wait_for_log("all running tasks finished"), session.read_log()


@then("the scheduler exited cleanly")
def scheduler_exited_cleanly(session):
    """A drained shutdown must report success."""
    assert session.wait_for_daemon_exit() == 0


@then("the grace period is reported as expired")
def grace_expired(session, task):
    """A run that outlives the grace period must be reported, not hidden."""
    assert task.elapsed < 10.0, "the daemon waited %.2fs for a 1s grace" % task.elapsed
    assert session.wait_for_log("grace period expired"), session.read_log()


@then("the run is recorded as canceled")
def run_recorded_as_canceled(session):
    """The run ended by the grace period must be logged as canceled."""
    assert session.wait_for_log("run canceled"), session.read_log()


# ------------------------------------------------- launcher selection (then)


@then("the provider received no command")
def no_command(session, task):
    """The agent launcher must leave the command empty.

    An empty command is the signal that the provider chooses the invocation. A
    defaulted command would be indistinguishable from a task that named one.
    """
    document = session.request_for(task.id)
    assert document["command"] == "", document["command"]


@then("the provider received no arguments")
def no_arguments(session, task):
    """A task that names no arguments must send none."""
    document = session.request_for(task.id)
    assert document["args"] is None, document["args"]


@then("the provider received the task content path")
def task_content_path(session, task):
    """The provider must receive the Markdown path it is asked to work on."""
    document = session.request_for(task.id)
    expected = os.path.join(session.tasks_root, task.id + ".md")
    assert document["task_path"] == expected, document["task_path"]


@then("the launch is refused because the launcher is unknown")
def launch_refused_unknown_launcher(session, task):
    """A task naming a missing launcher must be refused with the alternatives."""
    assert task.last["code"] != 0, "a task with an unknown launcher was launched"
    assert "unknown launcher" in task.last["err"], task.last["err"]


@then("the provider received the arguments the task named")
def arguments_named(session, task):
    """The arguments the task named must be sent unchanged."""
    document = session.request_for(task.id)
    assert document["args"] == ["-c", "echo named"], document["args"]
