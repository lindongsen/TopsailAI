"""Read pending first-record control proposals only. Author: DawsonLin."""
from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
from topsailai.ai_base.llm_control.request_control import REQUEST_CONTROL


def main(*, binding_id, generation, invocation_id, attempt_id, phase, remaining_budget=None):
    """Probe canonical state using detached scalar routing, without consumption."""
    target = AttemptTarget(binding_id, generation, invocation_id, attempt_id)
    return REQUEST_CONTROL.probe(target, phase)
