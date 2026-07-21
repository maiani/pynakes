# Agent beta evaluation

pynakes includes an opt-in harness for testing the CLI with a fresh agent in an
isolated sample workspace. The ordinary test suite uses a deterministic fake
provider; real-agent runs are manual because they invoke an external agent and
may use network-backed commands.

## Run the deterministic harness test

```bash
pytest tests/test_agent_beta_eval.py
```

This validates task generation, report parsing, output artifacts, and a final
`pynakes inspect --json` check without contacting an external service.

## Run a real Codex evaluation

Install and authenticate the Codex CLI, then explicitly enable the manual test:

```bash
PYNAKES_RUN_AGENT_EVAL=1 pytest \
  tests/test_agent_beta_eval.py::test_real_codex_agent_eval_manual -m agent_eval
```

The harness selects a deterministic set of offline tasks by default. Runs write
their task list, raw provider output, structured report, and Markdown summary
under `.agent-eval-runs/`; that directory is ignored by git.

To configure a run directly, invoke the runner module:

```bash
python -m tests.agent_eval.runner --provider codex --tasks 6 --seed 1
```

Use `--include-online` only when provider and publisher network calls are
intended. Network failures should be classified separately from product errors.
See `python -m tests.agent_eval.runner --help` for model, reasoning-effort,
timeout, strictness, and output-directory options.
