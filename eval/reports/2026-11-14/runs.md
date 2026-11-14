# ASR spike runs

Fillers = words ờ, à, ừm, ừ. Repeats = earlier copies of immediate repeats. Transcribe = wall time without model load. VRAM = rise in GPU memory used (nvidia-smi), CUDA only.

## 0ef0e720 (157.8 s)

| Model | Device | Load s | Transcribe s | RTF | Peak RAM MB | Peak VRAM MB | Words | Fillers | Repeats |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| crisperwhisper | cuda | 17.78 | 57.99 | 0.368 | 7943 | 5128 | 496 | 0 | 5 |
| phowhisper | cuda | 13.23 | 98.8 | 0.626 | 9329 | 6540 | 476 | 1 | 2 |
| whisper_baseline | cuda | 9.07 | 18.1 | 0.115 | 3118 | 4502 | 460 | 0 | 3 |

## 319af07b (41.8 s)

| Model | Device | Load s | Transcribe s | RTF | Peak RAM MB | Peak VRAM MB | Words | Fillers | Repeats |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| crisperwhisper | cuda | 17.78 | 25.98 | 0.622 | 7943 | 5128 | 257 | 0 | 0 |
| phowhisper | cuda | 13.23 | 40.07 | 0.959 | 9329 | 6540 | 260 | 0 | 1 |
| whisper_baseline | cuda | 9.07 | 10.09 | 0.242 | 3118 | 4550 | 249 | 0 | 0 |

## 5911f3b2 (31.6 s)

| Model | Device | Load s | Transcribe s | RTF | Peak RAM MB | Peak VRAM MB | Words | Fillers | Repeats |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| crisperwhisper | cuda | 17.78 | 13.83 | 0.438 | 7943 | 5128 | 103 | 0 | 0 |
| phowhisper | cuda | 13.23 | 21.01 | 0.665 | 9329 | 6506 | 100 | 0 | 0 |
| whisper_baseline | cuda | 9.07 | 3.87 | 0.123 | 3118 | 4466 | 100 | 0 | 0 |

## 633e80af (164.8 s)

| Model | Device | Load s | Transcribe s | RTF | Peak RAM MB | Peak VRAM MB | Words | Fillers | Repeats |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| crisperwhisper | cuda | 17.78 | 60.03 | 0.364 | 7943 | 5128 | 500 | 0 | 4 |
| phowhisper | cuda | 13.23 | 176.87 | 1.073 | 9329 | 6506 | 617 | 0 | 2 |
| whisper_baseline | cuda | 9.07 | 18.11 | 0.11 | 3118 | 4466 | 460 | 0 | 2 |

## c001 (160.9 s)

| Model | Device | Load s | Transcribe s | RTF | Peak RAM MB | Peak VRAM MB | Words | Fillers | Repeats |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| crisperwhisper | cuda | 17.78 | 89.99 | 0.559 | 7943 | 5128 | 746 | 1 | 7 |
| phowhisper | cuda | 13.23 | 229.87 | 1.428 | 9329 | 6471 | 570 | 4 | 8 |
| whisper_baseline | cuda | 9.07 | 29.93 | 0.186 | 3118 | 4466 | 692 | 1 | 3 |
