# Third-party notices

Sudarshan Agentic Core is MIT licensed under [LICENSE](LICENSE). This file
records the external software and reference repositories used by, vendored in,
or consulted for this project. A reference repository's license applies to its
own code and assets; it does not automatically relicense original Sudarshan
code or conceptual adaptations.

## Vendored or runtime-integrated software

### DeepSeek Harness

- Repository: [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)
- Local path: `deepseek-harness/`
- License: MIT
- Copyright: DeepSeek, 2026
- The vendored checkout retains its own [license](deepseek-harness/LICENSE).

### AntV Infographic

- Repository: [antvis/infographic](https://github.com/antvis/infographic)
- Integration: pinned `@antv/infographic` renderer under
  `pipelines/infographic/antv_renderer/`
- Upstream license: MIT, copyright AntV, 2025
- Sudarshan keeps the renderer behind a validated adapter and does not expose
  its editor or arbitrary runtime surface.

## Reference repositories

These repositories informed workflow, memory, diagram, presentation, video,
and skill design. The current adaptation ledgers record the implementation
boundary and should be updated if code or assets are copied in the future.

| Repository | License | Use in Sudarshan | Notice |
| --- | --- | --- | --- |
| [agentmemory](https://github.com/rohitg00/agentmemory) | Apache-2.0 | Reference for memory lifecycle, audit, and deduplication patterns; no runtime dependency | [adaptation ledger](docs/reference-adaptations/agentmemory.md) |
| [diagram-design](https://github.com/cathrynlavery/diagram-design) | MIT, Cathryn Lavery, 2025 | Design and validation ideas; native Sudarshan diagram implementation | [ledger](docs/reference-adaptations/diagram-design.md) |
| [infographic](https://github.com/antvis/infographic) | MIT, AntV, 2025 | Declarative infographic/SVG concepts and pinned renderer integration | [ledger](docs/reference-adaptations/antv-infographic.md) |
| [linkedin-skills](https://github.com/sergebulaev/linkedin-skills) | MIT, Sergey Bulaev, 2026 | Skill routing, approval, and untrusted-content patterns; no runtime dependency | [ledger](docs/reference-adaptations/linkedin-skills.md) |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | MIT, Harry, 2024 | Video task/timeline and asset-ledger concepts; no package import | [ledger](docs/reference-adaptations/moneyprinterturbo.md) |
| [MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3) | MiniMax H3 Community License Agreement | Audited as a possible external video provider and prompt reference; no weights/source/assets copied | [audit ledger](docs/reference-adaptations/minimax-h3.md) |
| [OpenViking](https://github.com/volcengine/OpenViking) | AGPL-3.0 for the main repository | L0/L1/L2 context design only; no OpenViking code or runtime dependency | [ledger](docs/reference-adaptations/openviking.md) |
| [ppt-master](https://github.com/hugohe3/ppt-master) | MIT, Hugo He, 2025-2026 | Round-trip PPT and page-local workflow concepts; no package import | [ledger](docs/reference-adaptations/ppt-master.md) |

### License boundary

- `agentmemory` is Apache-2.0, not MIT. Its license and notices must be kept
  if code is ever copied.
- The main OpenViking repository is AGPL-3.0. Its MIT-licensed bot directory
  and other third-party components do not make the whole repository MIT.
- Third-party assets, fonts, icons, templates, and provider media may have
  separate licenses. They require asset-level review before distribution.
- If future work copies upstream source rather than reimplementing a concept,
  retain the upstream copyright/license notice beside the copied material and
  update this file.
