#!/usr/bin/env python3
"""
KLayout Python Macro Template
Basic layout creation and manipulation
"""

import pya

def create_basic_layout():
    """Create a basic layout with simple geometry"""
    layout = pya.Layout()
    
    # Create top cell
    top_cell = layout.create_cell("TOP")
    
    # Define layers
    metal1 = layout.layer(1, 0)  # Metal 1
    via1 = layout.layer(2, 0)    # Via 1
    metal2 = layout.layer(3, 0)  # Metal 2
    
    # Add some shapes
    shapes = top_cell.shapes(metal1)
    
    # Rectangle
    shapes.insert(pya.DBox(0, 0, 10, 20))
    
    # Polygon
    points = [pya.DPoint(15, 0), pya.DPoint(25, 0), pya.DPoint(20, 15)]
    shapes.insert(pya.DPolygon(points))
    
    # Add via
    via_shapes = top_cell.shapes(via1)
    via_shapes.insert(pya.DBox(30, 0, 32, 2))
    
    # Add metal 2
    m2_shapes = top_cell.shapes(metal2)
    m2_shapes.insert(pya.DBox(30, 0, 40, 10))
    
    return layout

def main():
    """Main function to run the macro"""
    layout = create_basic_layout()
    
    # Save the layout
    output_file = "basic_layout.gds"
    layout.write(output_file)
    print(f"Layout saved to {output_file}")
    
    # Print some statistics
    print(f"Cells: {layout.cells()}")
    print(f"Layers: {len(list(layout.layer_infos()))}")

if __name__ == "__main__":
    main()