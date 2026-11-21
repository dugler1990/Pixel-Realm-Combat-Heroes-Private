# Upscale tab

A tab on the level review page. You start the pod in RunPod. The page is given that pod's Connect SSH line. The GPU is whatever you already chose there. The page connects, installs HYPIR-SD2, sends one level image, and shows the result.

## What you do

1. Start a pod in RunPod on a PyTorch CUDA image. Copy its Connect SSH line:
   `ssh root@HOST -p PORT -i ~/.ssh/id_ed25519`
2. Open the review page for the run, same server as now.
3. Open the Upscale tab, paste that line, press Connect.
4. The page connects and installs HYPIR-SD2. Status shows connecting, then installing, then ready.
5. The level on screen is the piece. Press Send. The page uploads that image, runs HYPIR, and shows the result beside it.
6. Stop the pod in RunPod when finished. The tab only disconnects. It does not terminate the pod. The bill stops when you stop the pod there.

## What gets sent

- Accepted image for that level when one exists. Otherwise the latest generated attempt.
- Result saved at `levels/<id>/upscale/hypir.png` and shown in the tab.
- Send again overwrites that file.

## How

Branch `feat/level-review-fit`, review server that already exists.

- Fourth tab in `web/review.html`, next to Align, Result, and Tests.
- Side panel for that tab: connection string, Connect, status line, Send.
- `POST /api/upscale/connect` parses the SSH line (user, host, port, key path) and opens SSH. The string stays in the server process for the session. It is not written into the repo.
- That call installs HYPIR when it is not already on the pod: clone the HYPIR repo, install its Python deps into a venv on the pod, download `HYPIR_sd2.pth` and Stable Diffusion 2.1 base. A later connect to the same pod skips the download.
- `GET /api/upscale/status` is what the tab polls.
- `POST /api/upscale/run` with the current level id uploads the image, runs HYPIR on that one file, copies the output back.

SSH is the system `ssh` client, batch mode, no prompts. A bad line or a stopped pod returns the SSH error in the status line. RunPod gives a new Connect line after the pod is started again.

One HYPIR pass at 2×. The tab also shows that result scaled back to the original size, so crispness is judged on the same crop. The prompt sent with it is a short line for painted ice ground.

## Out of this

- No RunPod API key.
- No GPU menu.
- The page does not create the pod.
- One model: HYPIR-SD2. The open weights are non-commercial. Fine for this test.
- The result does not replace the accepted level and does not go into Build map.

## Build order

1. Parse the SSH line and connect. Test never dials a real host.
2. Install script and status polling.
3. Send one level and display the pair.
4. The tab.
