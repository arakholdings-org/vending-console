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
    if not (0 <= tray_number <= 9):
        raise ValueError("Tray number must be between 0 and 9")

    selections = []
    start_selection = tray_number * 10

    # Create entries for each selection in the tray
    for i in range(10):  # 10 selections per tray
        selection_number = start_selection + i
        selection_data = {
            "selection": selection_number,
            "tray": tray_number,
            "price": price,
            "inventory": inventory,
            "capacity": 5,  # Fixed capacity per selection
        }
        selections.append(selection_data)

    return selections
