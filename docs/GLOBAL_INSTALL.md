# Global Shared Installation

Install the Control Tower once for every project owned by the current user:

```bash
scripts/install_global.sh
```

The installer publishes immutable code and policy artifacts under:

```text
~/.local/share/ollama-control-tower/
├── config/
├── docs/
├── scripts/
├── README.md
├── requirements.txt
└── INSTALLATION.json
```

It also creates `~/.local/bin/control-tower`, which activates the canonical
`/home/praveen/venv-ardupilot` environment before dispatching the shared CLI.
Because `~/.local/bin` is already on `PATH`, any project can run:

```bash
control-tower platform --strict
control-tower registry validate
control-tower supervisor validate
control-tower harness validate
control-tower monitor health
control-tower memory stats
```

Runtime databases and event files remain outside project repositories under
`~/.local/state/ollama-control-tower`. This allows projects to share the control
plane while keeping operational state out of Git.

Run the installer again after pulling or publishing a new repository commit.
`INSTALLATION.json` records the source checkout and installed Git revision so a
project can verify which global version it is using.

The installer does not add API keys, enable cloud providers, install PAIR, or
change system services. Provider and runtime activation remain explicit
deployment steps.
