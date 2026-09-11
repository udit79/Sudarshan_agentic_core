# Provider and model routing

Sudarshan has three different routing layers:

1. The request/pipeline router chooses the top-level transformation.
2. `SkillRuntime` chooses and governs typed child skills.
3. `ProviderRouter` chooses a configured model and protects provider calls for
   capabilities such as `image` and `tts`.

The third layer is intentionally small in the first slice. It is process-local
and should not become a second scheduler. The shared control plane can persist
the same health state when multi-worker deployment is enabled.

## Model selection

The current defaults are:

| Capability | Environment variable | Default |
| --- | --- | --- |
| text | `CREWAI_MODEL` | `openai/gpt-5.4` |
| image | `OPENAI_IMAGE_MODEL` | `gpt-image-1` |
| tts | `OPENAI_TTS_MODEL` | `tts-1` |
| video script | `OPENAI_VIDEO_SCRIPT_MODEL` | `gpt-5.4` |

An API key is only a configuration signal. It does not guarantee model access
or remaining quota.

## Failure handling

Provider errors are classified as `auth`, `quota_exhausted`, `rate_limit`,
`timeout`, `transient`, `invalid_request`, or `unknown`. Quota, authentication,
rate-limit, and transient failures open a short provider/capability cooldown.
Calls during cooldown fail fast, preventing a parallel retry storm.

The current media fallbacks are deliberately local:

- LinkedIn changes an image asset request to prompt-only output and adds the
  failure class to the caveat.
- Video uses a local FFmpeg title card when an image is unavailable and records
  `degraded: true` plus the per-scene failure class. Missing TTS becomes silent
  narration and is also recorded as degraded.
- PPT and infographic rendering remain local/deterministic where possible.

The frontend should display `degraded`, `degradation_reasons`, and the next
recommended user action. It must not claim that an image was generated when a
fallback was used.
