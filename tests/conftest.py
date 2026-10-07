import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import motor  # noqa: E402


@pytest.fixture
def cfg():
    """Configuração padrão do programa (sem ler o config.yaml do posto)."""
    return copy.deepcopy(motor.PADRAO)
