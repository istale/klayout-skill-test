#!/usr/bin/env python3
"""
KLayout Python Macro Template
Layer manipulation and region operations
"""

import pya

def layer_operations_example():
    """Demonstrate layer operations and region manipulation"""
    layout = pya.Layout()
    top_cell = layout.create_cell("REGION_DEMO")
    
    # Define layers
    layer1 = layout.layer(1, 0)
    layer2 = layout.layer(2, 0)
    
    # Create some polygons on layer1
    shapes1 = top_cell.shapes(layer1)
    shapes1.insert(pya.DBox(0, 0, 10, 10))
    shapes1.insert(pya.DBox(20, 0, 30, 10))
    
    # Create some polygons on layer2  
    shapes2 = top_cell.shapes(layer2)
    shapes2.insert(pya.DBox(5, 5, 15, 15))
    shapes2.insert(pya.DBox(25, 5, 35, 15))
    
    # Create regions from the shapes
    region1 = pya.Region(top_cell.shapes(layer1))
    region2 = pya.Region(top_cell.shapes(layer2))
    
    # Perform boolean operations
    union_region = region1 + region2
    intersection_region = region1 & region2
    difference_region = region1 - region2
    
    # Create new layers for results
    union_layer = layout.layer(10, 0)
    intersection_layer = layout.layer(11, 0)
    difference_layer = layout.layer(12, 0)
    
    # Write results back to layout
    top_cell.shapes(union_layer).insert(union_region)
    top_cell.shapes(intersection_layer).insert(intersection_region)
    top_cell.shapes(difference_layer).insert(difference_region)
    
    # Size operation example
    expanded_region = region1.sized(1.0)
    expanded_layer = layout.layer(13, 0)
    top_cell.shapes(expanded_layer).insert(expanded_region)
    
    return layout

def analyze_regions(layout):
    """Analyze and print region statistics"""
    top_cell = layout.cell(0)
    
    for layer_info in layout.layer_infos():
        layer_index = layout.layer(layer_info)
        region = pya.Region(top_cell.shapes(layer_index))
        
        print(f"Layer {layer_info.layer}/{layer_info.datatype}:")
        print(f"  Polygons: {region.polygons()}")
        print(f"  Area: {region.area() * layout.dbu**2:.2f} μm²")
        print(f"  Bounding box: {region.bbox()}")

def main():
    """Main function"""
    layout = layer_operations_example()
    
    print("Region Analysis:")
    analyze_regions(layout)
    
    # Save results
    layout.write("region_operations.gds")
    print("Layout saved to region_operations.gds")

if __name__ == "__main__":
    main()