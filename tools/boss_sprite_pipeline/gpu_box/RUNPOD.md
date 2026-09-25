# RunPod Gate A runbook

Use a disposable pod only for Stable Fast 3D mesh generation. Do not run rig
or animation during this trial. See [`../../../LEGAL_LIABILITY.md`](../../../LEGAL_LIABILITY.md)
for the selected model's revenue threshold and the reasons Hunyuan3D and
TRELLIS were rejected.

## Manual launch (the payment boundary)

If this Windows account has no SSH key yet, create a dedicated one in
PowerShell and press Enter twice when asked for a passphrase:

```powershell
ssh-keygen -t ed25519 -f "$HOME\.ssh\boss_gpu_trial" -C "boss-gpu-trial"
Get-Content "$HOME\.ssh\boss_gpu_trial.pub"
```

1. Add credit at <https://www.runpod.io/>.
2. Deploy one **RTX 3090 24 GB** Community Cloud pod.
3. Use image
   `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`.
4. Allocate at least **60 GB container disk**. A persistent network volume is
   unnecessary for this disposable run.
5. Add your SSH public key and expose TCP port 22.
6. Send the resulting SSH command (host, mapped port, and username) to the
   operator. Do not send a private key or API key.

At current Community Cloud pricing, a two-to-five-hour first session should
remain around USD 0.50-2.00. Verify the displayed price before deploying and
terminate the pod as soon as the artifacts have downloaded.

## Commands run after SSH access

The operator transfers the prepared worktree directly, so the pod needs no
GitHub credentials.

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git g++ rsync
curl -LsSf https://astral.sh/uv/0.8.17/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

cd /workspace/Pixel-Realm-Combat-Heroes-Boss
uv venv --python 3.11 tools/boss_sprite_pipeline/.venv-bpy
uv pip install --python tools/boss_sprite_pipeline/.venv-bpy/bin/python \
  "bpy==4.5.13" pillow numpy
bash tools/boss_sprite_pipeline/gpu_box/setup.sh stable_fast_3d

# The user performs this interactively after accepting the model terms.
tools/boss_sprite_pipeline/gpu_box/vendor/stable_fast_3d/.venv/bin/huggingface-cli login

tools/boss_sprite_pipeline/.venv-bpy/bin/python \
  -m tools.boss_sprite_pipeline.pipeline \
  tools/boss_sprite_pipeline/bosses/demon.json --from mesh --to mesh
```

Expected outputs:

```text
generated/bosses/demon/mesh/raw.glb
generated/bosses/demon/mesh/turntable.png
generated/bosses/demon/state.json
```

Download those files and the command logs before terminating the pod.

## Required Hugging Face action

Before generation, the user must:

1. Sign in and accept the model terms at
   <https://huggingface.co/stabilityai/stable-fast-3d>.
2. Create a fine-grained read token at <https://huggingface.co/settings/tokens>.
3. Enter that token directly into `huggingface-cli login` on the pod. Do not
   send the token to another person or commit it to the repository.
