"""Split per-flight YOLO data into train/val/test by flight and write data.yaml.

Expected source layout (e.g. one Label Studio YOLO export per flight):
    data/own/flight01/images/*.jpg
    data/own/flight01/labels/*.txt
    data/own/flight01/classes.txt   (optional, from the export; class ids are remapped by name)
"""
import argparse
import shutil
from collections import Counter
from pathlib import Path

CLASSES = ["pedestrian", "vehicle", "tree", "building", "other_obstacles"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def normalize(name):
    """'Other _Obstacles', 'other obstacles' and 'other_obstacles' all become 'other_obstacles'."""
    return "_".join(name.strip().lower().replace("_", " ").split())


def read_class_map(flight):
    """Map the export's class ids to CLASSES ids, using the export's classes.txt if present."""
    classes_txt = flight / "classes.txt"
    if not classes_txt.exists():
        return {i: i for i in range(len(CLASSES))}
    names = [normalize(line) for line in classes_txt.read_text().splitlines() if line.strip()]
    unknown = [name for name in names if name not in CLASSES]
    if unknown:
        raise ValueError(f"{classes_txt}: unknown class names {unknown}, expected only {CLASSES}")
    return {i: CLASSES.index(name) for i, name in enumerate(names)}


def prepare_dataset(source_dir, output_dir, val_flights, test_flights):
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    flights = sorted(p for p in source_dir.iterdir() if (p / "images").is_dir())
    if not flights:
        raise FileNotFoundError(f"No <flight>/images folders found in {source_dir}")

    unknown = set(val_flights + test_flights) - {f.name for f in flights}
    if unknown:
        raise ValueError(f"Unknown flight names: {sorted(unknown)}")

    images_per_split = Counter()
    boxes_per_class = Counter()
    for flight in flights:
        split = "val" if flight.name in val_flights else "test" if flight.name in test_flights else "train"
        class_map = read_class_map(flight)
        image_dir = output_dir / split / "images"
        label_dir = output_dir / split / "labels"
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)

        for image in sorted((flight / "images").iterdir()):
            if image.suffix.lower() not in IMAGE_EXTS:
                continue
            # Prefix with the flight name so frames from different flights never collide
            name = f"{flight.name}_{image.stem}"
            shutil.copy2(image, image_dir / f"{name}{image.suffix}")

            label = flight / "labels" / f"{image.stem}.txt"
            out_label = label_dir / f"{name}.txt"
            if label.exists():
                lines = []
                for line in label.read_text().splitlines():
                    if line.strip():
                        class_id, *coords = line.split()
                        if int(class_id) not in class_map:
                            raise ValueError(f"{label}: class id {class_id} is not in {flight / 'classes.txt'}")
                        new_id = class_map[int(class_id)]
                        lines.append(" ".join([str(new_id), *coords]))
                        boxes_per_class[CLASSES[new_id]] += 1
                out_label.write_text("\n".join(lines) + "\n" if lines else "")
            else:
                out_label.touch()  # no label file = background frame, keep it
            images_per_split[split] += 1

    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(CLASSES))
    (output_dir / "data.yaml").write_text(
        f"path: {output_dir.resolve()}\n"
        "train: train/images\n"
        "val: val/images\n"
        "test: test/images\n"
        f"names:\n{names}\n"
    )

    print("Images per split:", dict(images_per_split))
    print("Boxes per class:", {name: boxes_per_class[name] for name in CLASSES})
    print(f"Wrote {output_dir / 'data.yaml'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split per-flight YOLO data by flight and write data.yaml.")
    parser.add_argument("--source_dir", required=True, help="Folder containing one subfolder per flight")
    parser.add_argument("--output_dir", required=True, help="Where to write train/val/test and data.yaml")
    parser.add_argument("--val", nargs="+", required=True, help="Flight folder names to use for validation")
    parser.add_argument("--test", nargs="*", default=[], help="Flight folder names to hold out for testing")
    args = parser.parse_args()
    prepare_dataset(args.source_dir, args.output_dir, args.val, args.test)
