# Judge Upload Sample Run Report

Sample bundle: `demo_assets/judge_upload_sample.zip`

Local package validation:

- Exactly one IDF: pass
- Exactly one EPW: pass
- Support README: accepted text
- Detected IDF version: 26.1
- Server compatibility: pass against 26.1.0
- Source changes required: none

Real official MCP run:

- Isolated run: `7bc1ac40...`
- Simulation mode: Standard EnergyPlus
- Simulation launch calls: 1
- MCP wait duration: 87.019 seconds
- Generated files: 20
- Fatal errors: 0
- Severe errors: 0
- Warnings: 5
- Interactive plot: generated

Warnings include a weather/location mismatch because the uploaded San
Francisco EPW differs from the model's Denver `Site:Location`, two barometric
pressure notices, and two cooling-coil performance warnings. The original
EnergyPlus log is preserved in the run workspace.

This was exercised through the same validator, workspace, MCP client, and tool
guard used by the dashboard. The browser upload clicks themselves were
render-tested with Streamlit AppTest, not manually replayed by Codex.
