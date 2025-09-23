# astra_monitor_server/gui/custom_items.py

from PyQt5.QtWidgets import QTreeWidgetItem
from PyQt5.QtCore import Qt

class SortableTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, otherItem):
        column = self.treeWidget().sortColumn()
        
        # CPU, Mem, Disk %
        if column in [3, 4, 5]:
            try:
                self_val_str = self.text(column).split('%')[0].strip()
                other_val_str = otherItem.text(column).split('%')[0].strip()
                return float(self_val_str) < float(other_val_str)
            except (ValueError, IndexError):
                return self.text(column) < otherItem.text(column)
        
        # Network speed (sort by download speed)
        if column == 6:
            try:
                self_text = self.text(column).split('/')[0].strip().lower()
                other_text = otherItem.text(column).split('/')[0].strip().lower()

                def to_bytes(s):
                    parts = s.split()
                    if len(parts) < 2: return 0
                    val_str, unit = parts
                    val = float(val_str)
                    if 'mb' in unit: return val * 1024 * 1024
                    if 'kb' in unit: return val * 1024
                    if 'b' in unit: return val
                    return 0
                
                return to_bytes(self_text) < to_bytes(other_text)
            except (ValueError, IndexError, AttributeError):
                return self.text(column) < otherItem.text(column)

        # Default string comparison
        return super().__lt__(otherItem)