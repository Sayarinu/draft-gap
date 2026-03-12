from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn as nn


class WinProbabilityMLP(nn.Module):

    def __init__(self, input_dim: int, hidden: tuple[int, ...] = (128, 64, 32)) -> None:
        super().__init__()
        dims = [input_dim] + list(hidden) + [1]
        layers: list[nn.Module] = []
        for i in range(len(dims) - 1):
            layers.append(nn.Linear(dims[i], dims[i + 1]))
            if i < len(dims) - 2:
                layers.append(nn.ReLU())
                layers.append(nn.Dropout(0.1))
        layers.append(nn.Sigmoid())
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def train_step(
    model: WinProbabilityMLP,
    X: torch.Tensor,
    y: torch.Tensor,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    device: torch.device,
    sample_weights: torch.Tensor | None = None,
) -> float:
    model.train()
    X, y = X.to(device), y.to(device)
    if sample_weights is not None:
        sample_weights = sample_weights.to(device)
    optimizer.zero_grad()
    logits = model(X)
    if sample_weights is not None:
        loss_per = criterion(logits, y)
        loss = (sample_weights * loss_per).sum() / sample_weights.sum().clamp(min=1e-8)
    else:
        loss = criterion(logits, y)
    loss.backward()
    optimizer.step()
    return loss.item()


def evaluate(model: WinProbabilityMLP, X: np.ndarray, y: np.ndarray, device: torch.device) -> float:
    model.eval()
    with torch.no_grad():
        Xt = torch.from_numpy(X).float().to(device)
        logits = model(Xt)
        pred = (logits >= 0.5).cpu().numpy().astype(np.float32)
    return float(np.mean(pred == y))


def save_model(
    model: WinProbabilityMLP,
    path: str | Path,
    input_dim: int,
    feature_names: list[str],
) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    state = {
        "state_dict": model.state_dict(),
        "input_dim": input_dim,
        "feature_names": feature_names,
    }
    torch.save(state, path / "win_probability_model.pt")


def load_model(path: str | Path, device: torch.device) -> tuple[WinProbabilityMLP, list[str]]:
    path = Path(path) / "win_probability_model.pt"
    state: dict[str, object] = torch.load(path, map_location=device, weights_only=False)
    input_dim = state["input_dim"]
    feature_names = state.get("feature_names", [])
    model = WinProbabilityMLP(input_dim=input_dim)
    model.load_state_dict(state["state_dict"])
    model.to(device)
    model.eval()
    return model, feature_names
