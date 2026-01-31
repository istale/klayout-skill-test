#!/usr/bin/env python3
"""
KLayout Python Macro Template
Hierarchical layout creation with instances
"""

import pya

def create_subcells(layout):
    """Create subcells that will be instanced"""
    # Create a simple transistor cell
    transistor = layout.create_cell("TRANSISTOR")
    active = layout.layer(1, 0)
    poly = layout.layer(2, 0)
    
    # Active region
    transistor.shapes(active).insert(pya.DBox(0, 0, 2, 1))
    # Polysilicon gate
    transistor.shapes(poly).insert(pya.DBox(0.8, -0.5, 1.2, 1.5))
    
    # Create a contact cell
    contact = layout.create_cell("CONTACT")
    metal1 = layout.layer(3, 0)
    via = layout.layer(4, 0)
    
    # Via
    contact.shapes(via).insert(pya.DBox(0, 0, 0.2, 0.2))
    # Metal1 connection
    contact.shapes(metal1).insert(pya.DBox(-0.1, -0.1, 0.3, 0.3))
    
    return transistor, contact

def create_hierarchical_layout():
    """Create a hierarchical layout using instances"""
    layout = pya.Layout()
    
    # Create subcells
    transistor, contact = create_subcells(layout)
    
    # Create top cell
    top_cell = layout.create_cell("TOP")
    
    # Place transistor instances
    trans_instances = [
        pya.DCellInstArray(transistor.cell_index(), pya.DTrans(0, 0)),
        pya.DCellInstArray(transistor.cell_index(), pya.DTrans(4, 0)),
        pya.DCellInstArray(transistor.cell_index(), pya.DTrans(8, 0)),
    ]
    
    for instance in trans_instances:
        top_cell.insert(instance)
    
    # Place contacts between transistors
    contact_instances = [
        pya.DCellInstArray(contact.cell_index(), pya.DTrans(2, 0.2)),
        pya.DCellInstArray(contact.cell_index(), pya.DTrans(6, 0.2)),
    ]
    
    for instance in contact_instances:
        top_cell.insert(instance)
    
    # Add routing
    metal1 = layout.layer(3, 0)
    routing = top_cell.shapes(metal1)
    routing.insert(pya.DBox(0.1, 0.2, 9.9, 0.4))
    
    return layout

def print_hierarchy(layout, cell_index=0, indent=0):
    """Print the layout hierarchy"""
    cell = layout.cell(cell_index)
    print("  " * indent + f"Cell: {cell.name}")
    
    for child in cell.each_child_cell():
        print_hierarchy(layout, child, indent + 2)

def analyze_instances(layout):
    """Analyze instances in the layout"""
    top_cell = layout.cell("TOP")
    
    print(f"Total instances in TOP: {top_cell.insts()}")
    
    for instance in top_cell.each_inst():
        ref_cell = layout.cell(instance.cell_inst.cell_index)
        trans = instance.trans
        print(f"Instance of {ref_cell.name} at ({trans.disp.x * layout.dbu:.2f}, {trans.disp.y * layout.dbu:.2f})")

def main():
    """Main function"""
    layout = create_hierarchical_layout()
    
    print("Layout Hierarchy:")
    print_hierarchy(layout)
    
    print("\nInstance Analysis:")
    analyze_instances(layout)
    
    # Save layout
    layout.write("hierarchical_layout.gds")
    print("\nLayout saved to hierarchical_layout.gds")
    
    # Print statistics
    print(f"\nTotal cells: {layout.cells()}")
    print(f"Total instances: {sum(cell.insts() for cell in layout.each_cell())}")

if __name__ == "__main__":
    main()