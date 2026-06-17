# visa_bulletin hosting topology

> Concrete hosting topology for this project — production/standby/staging hosts, IPs, hardware, the staging/standby/cutover mechanics, backup wiring, and DR — lives in the **private ops repo** (`visa_bulletin_platform/hosting/`) and the agent's private refs, **not** in this public repository.

Public rules use **abstract roles** (production / staging / data-pipeline server). For the host-agnostic deploy process, branch model, perf-baseline discipline, and smoke tests, see `deployment.md` and `branching.md`.
