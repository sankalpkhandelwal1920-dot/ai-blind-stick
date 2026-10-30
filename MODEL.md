# Model & Training

The road-object detector was fine-tuned from Ultralytics YOLOv8 on the
**India Driving Dataset (IDD)**. This document records the dataset, training
setup, results, and the reasoning behind the architecture choice.

## Dataset

- **Source:** India Driving Dataset (IDD) — Detection subset
- **Images:** ~31,500 training / ~10,200 validation
- **Annotations:** converted from Pascal VOC XML to YOLO format
- **Classes (15):** person, rider, car, truck, bus, motorcycle, bicycle,
  autorickshaw, tempo, animal, traffic sign, billboard, vehicle fallback,
  obstacle, traffic light

IDD was chosen deliberately over COCO/other driving datasets because it captures
the actual traffic the device is meant to help with — autorickshaws, mixed
two-wheeler traffic, and unstructured Indian roads that Western datasets miss.

## Training setup

| Setting | Value |
|---------|-------|
| Base model | `yolov8s` (fine-tuned) |
| Epochs | 60 |
| Image size | 640 |
| Batch size | 32 |
| GPU | NVIDIA A100 |
| Optimizer | auto (SGD-family) |
| Augmentation | mosaic (closed for final 10 epochs) |

## Results

Final validation metrics for the `yolov8s` model:

| Metric | Value |
|--------|:-----:|
| mAP@0.5 | 0.457 |
| mAP@0.5:0.95 | 0.293 |
| precision | 0.67 |
| recall | 0.41 |

### Per-class mAP@0.5

| Class | yolov8n (nano) | yolov8s (small) | Δ |
|-------|:--------------:|:---------------:|:---:|
| bus | 0.658 | **0.716** | +0.058 |
| autorickshaw | 0.641 | **0.707** | +0.066 |
| car | 0.629 | **0.679** | +0.050 |
| motorcycle | 0.616 | **0.668** | +0.052 |
| truck | 0.572 | **0.643** | +0.071 |
| rider | 0.510 | **0.566** | +0.056 |
| person | 0.452 | **0.527** | +0.075 |
| bicycle | 0.330 | **0.463** | +0.133 |
| **overall** | **0.388** | **0.457** | **+0.069** |

Rare classes (tempo, animal, traffic light, vehicle fallback) score low in both
models because they have very few training examples — tempo, for instance, has
only 11 instances in the validation set. These are not the safety-critical classes
for a navigation aid, so the low scores are acceptable.

## Why nano → small

The first model was `yolov8n` (nano, ~3M parameters). It plateaued at 0.388 mAP@0.5
after a full 60-epoch run — the loss and validation metrics flattened well before
the end, which indicated the bottleneck was **model capacity**, not training time or
data.

Rather than add epochs (which would not have helped a saturated nano model), the
architecture was upgraded to `yolov8s` (~11M parameters) and retrained on the same
data. This lifted every safety-critical class by 5–13 points and overall mAP@0.5 by
~0.07 — confirming the diagnosis.

### The trade-off

`yolov8s` is ~3.5× the parameters of nano, so it is more accurate but slower at
inference on a Raspberry Pi 4. For a real-time assistive device, that latency
matters. The repo keeps **both** models so the deployment can choose:

- **nano** — lower latency, for responsive live use
- **small** — higher accuracy, for validation and favourable conditions

Being explicit about the accuracy/latency trade-off, rather than just shipping the
"best" number, reflects the real engineering constraint of running on-device.

## Getting the weights

Trained weights are distributed via [GitHub Releases](../../releases), not committed
to git (they are 6–22 MB binaries that git handles poorly):

- `best_s.pt` — yolov8s, ~22 MB (higher accuracy)
- `best_n.pt` — yolov8n, ~6 MB (lower latency)

Place the chosen file at `/home/pi/` and point `IDD_MODEL` in `src/blindstick.py`
at it.
