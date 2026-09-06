# MoneyPrinterTurbo provider integration

This directory contains the Sudarshan-side adapter for the upstream
[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) worker. The
worker is not vendored and is not imported into the Sudarshan process.

The adapter follows the upstream V1 contract:

1. `POST /api/v1/videos` with `video_subject`, optional `video_script`, and
   supported `VideoParams` options;
2. read the returned `task_id`;
3. poll `GET /api/v1/tasks/{task_id}`;
4. return the worker's `videos` or `combined_videos` references unchanged.

The upstream worker owns rendering, FFmpeg, TTS, material providers, task
storage, and API authentication. Sudarshan owns request understanding,
memory policy, orchestration, and the provider-neutral artifact envelope.

Configure the boundary in the application environment:

```env
MONEYPRINTERTURBO_BASE_URL=http://127.0.0.1:8080
MONEYPRINTERTURBO_API_KEY=
```

No provider call is made during repository tests or setup. The real worker
must be started separately before a production video request is submitted.
