# To do

Open work that is not tied to a feature. Remove an item when it is done; if
it changes what the documentation claims, update that page in the same
change.

## Verify on real hardware

These were changed without the hardware to try them on. Each guide says so
in its own "not verified" note; take the note out once the item is done.

- [ ] **CUDA worker on Python 3.14.** Build it
  (`docker compose -f compose.yaml -f compose.gpu.yaml build worker`) and
  transcribe one file on an NVIDIA GPU. So far only checked: the PyTorch
  index has Python 3.14 builds of `torch 2.14.1+cu126`, `torchaudio` and
  `torchcodec`. See [GPU](how-to/gpu.md).
- [ ] **Vulkan worker on Python 3.14.** Build it and transcribe one file on
  an AMD or Intel GPU. Not built since the move to 3.14. See
  [Vulkan](how-to/vulkan.md).
- [ ] **A real transcription on the CPU worker on Python 3.14.** The image
  builds and its speech libraries import; no model has been loaded and no
  audio processed since the move.
- [ ] **`./scripts/mac.sh up` on a Mac.** Never run on one: the script is
  tested on Linux against stand-ins for Docker, Homebrew, uv and the worker.
  Check in particular that Homebrew's `whisper-cpp` provides `whisper-cli`,
  that Whisper uses Metal, and that the speaker model runs on `mps`. See
  [Metal](how-to/metal.md).
