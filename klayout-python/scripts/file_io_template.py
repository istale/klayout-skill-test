#!/usr/bin/env python3
"""
KLayout Python Macro Template
File I/O and layout processing utilities
"""

import pya
import os

def process_existing_layout(input_file, output_file):
    """Process an existing layout file"""
    if not os.path.exists(input_file):
        print(f"Input file {input_file} not found")
        return None
    
    # Load layout
    layout = pya.Layout()
    layout.read(input_file)
    
    print(f"Loaded {input_file}")
    print(f"  Cells: {layout.cells()}")
    print(f"  Layers: {len(list(layout.layer_infos()))}")
    print(f"  Database units: {layout.dbu}")
    
    # Analyze the layout
    analyze_layout(layout)
    
    # Add a new cell with processing results
    add_info_cell(layout)
    
    # Save processed layout
    layout.write(output_file)
    print(f"Processed layout saved to {output_file}")
    
    return layout

def analyze_layout(layout):
    """Analyze and print layout statistics"""
    print("\nLayout Analysis:")
    
    total_shapes = 0
    layer_stats = {}
    
    for cell in layout.each_cell():
        cell_shapes = 0
        for layer_info in layout.layer_infos():
            layer_index = layout.layer(layer_info)
            shapes = len(list(cell.shapes(layer_index).each()))
            cell_shapes += shapes
            
            layer_key = f"{layer_info.layer}/{layer_info.datatype}"
            if layer_key not in layer_stats:
                layer_stats[layer_key] = 0
            layer_stats[layer_key] += shapes
        
        total_shapes += cell_shapes
        print(f"  Cell '{cell.name}': {cell_shapes} shapes")
    
    print(f"\nLayer Statistics:")
    for layer, count in sorted(layer_stats.items()):
        print(f"  Layer {layer}: {count} shapes")
    
    print(f"\nTotal shapes: {total_shapes}")

def add_info_cell(layout):
    """Add an information cell with layout statistics"""
    info_cell = layout.create_cell("LAYOUT_INFO")
    text_layer = layout.layer(255, 0)  # Text layer
    
    # Add text information
    info_text = [
        f"Total cells: {layout.cells()}",
        f"Database units: {layout.dbu}",
        f"Layers: {len(list(layout.layer_infos()))}",
    ]
    
    y_offset = 0
    for text in info_text:
        text_shape = pya.DText(text, 10, pya.DTrans(0, y_offset))
        info_cell.shapes(text_layer).insert(text_shape)
        y_offset += 15

def convert_format(input_file, output_format):
    """Convert between different layout formats"""
    if not os.path.exists(input_file):
        print(f"Input file {input_file} not found")
        return
    
    layout = pya.Layout()
    layout.read(input_file)
    
    # Determine output filename
    base_name = os.path.splitext(input_file)[0]
    if output_format.lower() == "oas":
        output_file = f"{base_name}.oas"
    elif output_format.lower() == "gds":
        output_file = f"{base_name}.gds"
    else:
        print(f"Unsupported format: {output_format}")
        return
    
    # Configure save options
    options = pya.SaveLayoutOptions()
    if output_format.lower() == "oas":
        options.format = "OASIS"
    else:
        options.format = "GDS2"
    
    # Save with specific options
    layout.write(output_file, options)
    print(f"Converted {input_file} to {output_file}")

def extract_layers(input_file, output_file, layer_list):
    """Extract specific layers from a layout"""
    if not os.path.exists(input_file):
        print(f"Input file {input_file} not found")
        return
    
    layout = pya.Layout()
    layout.read(input_file)
    
    # Create new layout for extracted layers
    new_layout = pya.Layout()
    new_layout.dbu = layout.dbu
    
    # Copy only specified layers
    top_cell = layout.cell(0)
    if top_cell:
        new_top = new_layout.create_cell(top_cell.name)
        
        for layer_spec in layer_list:
            # Parse layer specification "layer/datatype"
            if "/" in layer_spec:
                layer, datatype = map(int, layer_spec.split("/"))
            else:
                layer = int(layer_spec)
                datatype = 0
            
            # Find matching layer in original layout
            for layer_info in layout.layer_infos():
                if layer_info.layer == layer and layer_info.datatype == datatype:
                    # Copy layer to new layout
                    new_layer = new_layout.layer(layer, datatype)
                    old_layer = layout.layer(layer_info)
                    
                    # Copy shapes
                    for shape in top_cell.shapes(old_layer).each():
                        new_top.shapes(new_layer).insert(shape.dup())
                    break
    
    new_layout.write(output_file)
    print(f"Extracted layers {layer_list} to {output_file}")

def batch_process_files(directory, pattern="*.gds"):
    """Process multiple files in a directory"""
    import glob
    
    files = glob.glob(os.path.join(directory, pattern))
    print(f"Found {len(files)} files to process")
    
    for input_file in files:
        base_name = os.path.splitext(input_file)[0]
        output_file = f"{base_name}_processed.gds"
        
        try:
            process_existing_layout(input_file, output_file)
        except Exception as e:
            print(f"Error processing {input_file}: {e}")

def main():
    """Main function demonstrating file I/O operations"""
    print("KLayout File I/O Examples")
    
    # Example 1: Process existing layout
    # process_existing_layout("input.gds", "output.gds")
    
    # Example 2: Convert format
    # convert_format("input.gds", "oas")
    
    # Example 3: Extract layers
    # extract_layers("input.gds", "extracted.gds", ["1/0", "2/0"])
    
    # Example 4: Batch process
    # batch_process_files("./layouts/", "*.gds")
    
    print("Uncomment the examples above to test different file operations")

if __name__ == "__main__":
    main()