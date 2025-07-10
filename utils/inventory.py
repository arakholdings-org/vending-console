from typing import Dict, List
from tinydb import Query


def create_tray_data(tray_number: int, price: int, inventory: int = 5) -> List[Dict]:
    """
    Create data structure for a tray and its selections
    Args:
        tray_number: Tray number (0-9)
        price: Price in cents
        inventory: Initial inventory count (default 5)

    Returns:
        List of dictionaries containing selection data for the tray
    """
    if tray_number < 0:
        raise ValueError("Tray number must be >= 0")

    selections = []
    start_selection = tray_number * 10 + 1  # 1, 11, 21, ...

    for i in range(10):
        selection_number = start_selection + i
        selection_data = {
            "selection": selection_number,
            "tray": tray_number,
            "price": price,
            "inventory": inventory,
            "capacity": 5,  # Always 5
        }
        selections.append(selection_data)

    return selections
