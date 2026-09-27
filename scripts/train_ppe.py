"""Обучение классификаторов средств защиты на размеченных открытых наборах.

Зачем это вместо сравнения текстовых фраз:нулевой CLIP на каске давал полноту 0,82 при
точности 0,69, и каждая третья отметка была ложной. Разметка у открытых наборов есть,
задача простая — два класса, — и небольшая обученная сеть решает её заметно лучше.

Вырезки делаются **той же геометрией, что в работе**: голова с плечами из рамки человека
и фигура целиком. Иначе обученное на чужих рамках не перенеслось бы на наш детектор людей.

Запуск: python scripts/train_ppe.py --kind head|vest
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DATA_ROOT = Path("data/ppe_train")
WEIGHTS_ROOT = Path("models/ppe")
INPUT_SIZE = {"head": 96, "vest": 128}
EPOCHS = 8
BATCH = 32
LEARNING_RATE = 3e-4
WORKERS = 2
CLASSES = 2


def build_loaders(kind: str, size: int):
    """Готовит выборки: обучающую с дрожанием и проверочные без него."""
    import torch
    from torchvision import datasets, transforms

    train_steps = transforms.Compose([
        transforms.Resize((size, size)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2),
        transforms.RandomAffine(degrees=8, translate=(0.05, 0.05), scale=(0.9, 1.1)),
        transforms.ToTensor(),
    ])
    plain_steps = transforms.Compose([transforms.Resize((size, size)), transforms.ToTensor()])
    loaders = {}
    for split, steps, shuffle in (("train", train_steps, True), ("valid", plain_steps, False), ("test", plain_steps, False)):
        folder = datasets.ImageFolder(str(DATA_ROOT / kind / split), transform=steps)
        loaders[split] = torch.utils.data.DataLoader(
            folder, batch_size=BATCH, shuffle=shuffle, num_workers=WORKERS
        )
        logger.info("%s: примеров %d, по классам %s", split, len(folder), _counts(folder))
    return loaders


def _counts(folder) -> dict[str, int]:
    """Сколько примеров каждого класса в выборке."""
    found: dict[str, int] = {}
    for _, label in folder.samples:
        name = folder.classes[label]
        found[name] = found.get(name, 0) + 1
    return found


def build_model():
    """Небольшая сеть под две метки: голова в каске или без, фигура в жилете или без."""
    import torch
    from torchvision.models import ResNet18_Weights, resnet18

    model = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
    model.fc = torch.nn.Linear(model.fc.in_features, CLASSES)
    return model


def class_weights(loader):
    """Веса классов: редкого класса в наборах заметно меньше, и без весов сеть его игнорирует."""
    import torch

    counts = [0] * CLASSES
    for _, label in loader.dataset.samples:
        counts[label] += 1
    total = sum(counts)
    weights = torch.tensor([total / (CLASSES * max(count, 1)) for count in counts], dtype=torch.float32)
    logger.info("Веса классов: %s", [round(float(value), 2) for value in weights])
    return weights


def run_epoch(model, loader, criterion, optimizer=None) -> tuple[float, float]:
    """Прогоняет выборку; с оптимизатором — обучение, без него — проверка."""
    import torch

    training = optimizer is not None
    model.train(training)
    total = correct = 0
    loss_sum = 0.0
    with torch.set_grad_enabled(training):
        for images, labels in loader:
            output = model(images)
            loss = criterion(output, labels)
            if training:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            loss_sum += float(loss.detach()) * len(labels)
            correct += int((output.argmax(1) == labels).sum())
            total += len(labels)
    return loss_sum / max(total, 1), correct / max(total, 1)


def main() -> int:
    """Учит классификатор и сохраняет веса."""
    import torch

    parser = argparse.ArgumentParser(description="Обучение проверок СИЗ")
    parser.add_argument("--kind", choices=("head", "vest"), required=True)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    args = parser.parse_args()

    size = INPUT_SIZE[args.kind]
    loaders = build_loaders(args.kind, size)
    model = build_model()
    criterion = torch.nn.CrossEntropyLoss(weight=class_weights(loaders["train"]))
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)
    best = 0.0
    WEIGHTS_ROOT.mkdir(parents=True, exist_ok=True)
    target = WEIGHTS_ROOT / f"{args.kind}.pt"
    for epoch in range(1, args.epochs + 1):
        train_loss, train_accuracy = run_epoch(model, loaders["train"], criterion, optimizer)
        valid_loss, valid_accuracy = run_epoch(model, loaders["valid"], criterion)
        logger.info(
            "эпоха %d: обучение %.3f/%.3f, проверка %.3f/%.3f",
            epoch, train_loss, train_accuracy, valid_loss, valid_accuracy,
        )
        if valid_accuracy > best:
            best = valid_accuracy
            torch.save({"state": model.state_dict(), "size": size, "classes": loaders["train"].dataset.classes}, target)
    test_loss, test_accuracy = run_epoch(model, loaders["test"], criterion)
    logger.info("Отложенная выборка: точность %.3f, веса записаны в %s", test_accuracy, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
