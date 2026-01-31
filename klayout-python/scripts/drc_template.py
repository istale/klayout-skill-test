#!/usr/bin/env python3
"""
KLayout Python Macro Template
DRC (Design Rule Check) operations
"""

import pya

def create_test_layout():
    """Create a test layout with DRC violations"""
    layout = pya.Layout()
    top_cell = layout.create_cell("DRC_TEST")
    
    # Define layers
    metal1 = layout.layer(1, 0)
    
    shapes = top_cell.shapes(metal1)
    
    # Add shapes with intentional DRC violations
    # Shape 1: OK
    shapes.insert(pya.DBox(0, 0, 10, 2))  # Width = 10 (OK)
    
    # Shape 2: Too narrow (width < 0.5)
    shapes.insert(pya.DBox(0, 5, 0.3, 7))  # Width = 0.3 (Violation)
    
    # Shape 3: Too close to shape 4 (spacing < 0.5)
    shapes.insert(pya.DBox(5, 10, 15, 12))
    shapes.insert(pya.DBox(15.3, 10, 25, 12))  # Spacing = 0.3 (Violation)
    
    # Shape 4: OK spacing
    shapes.insert(pya.DBox(5, 15, 15, 17))
    shapes.insert(pya.DBox(16, 15, 26, 17))  # Spacing = 1.0 (OK)
    
    return layout

def run_drc_checks(layout):
    """Run DRC checks and report violations"""
    drc = pya.DRCWriter(layout)
    top_cell = layout.cell("DRC_TEST")
    metal1 = layout.layer(1, 0)
    
    # Define DRC rules
    print("Running DRC checks...")
    
    # Minimum width check
    drc.min_width(metal1, 0.5)  # Minimum width = 0.5 μm
    
    # Minimum spacing check
    drc.min_spacing(metal1, 0.5)  # Minimum spacing = 0.5 μm
    
    # Run DRC
    drc.run(top_cell)
    
    # Get results
    errors = drc.errors()
    
    print(f"\nDRC Results: {len(errors)} violations found")
    
    # Analyze errors
    width_violations = []
    spacing_violations = []
    
    for error in errors:
        if "width" in error.type.lower():
            width_violations.append(error)
        elif "spacing" in error.type.lower():
            spacing_violations.append(error)
    
    print(f"  Minimum width violations: {len(width_violations)}")
    print(f"  Minimum spacing violations: {len(spacing_violations)}")
    
    return errors

def manual_drc_checks(layout):
    """Manual DRC checks using Region operations"""
    top_cell = layout.cell("DRC_TEST")
    metal1 = layout.layer(1, 0)
    
    print("\nManual DRC checks:")
    
    # Get all shapes on metal1
    region = pya.Region(top_cell.shapes(metal1))
    shapes = region.polygons()
    
    print(f"Total shapes: {len(shapes)}")
    
    # Check minimum width manually
    min_width_violations = 0
    min_width = 0.5 / layout.dbu  # Convert to database units
    
    for i, poly in enumerate(shapes):
        bbox = poly.bbox()
        width = min(bbox.width(), bbox.height())
        
        if width < min_width:
            min_width_violations += 1
            print(f"  Shape {i}: width violation ({width * layout.dbu:.2f} < 0.5)")
    
    print(f"  Manual minimum width violations: {min_width_violations}")
    
    # Check spacing manually
    min_spacing_violations = 0
    min_spacing = 0.5 / layout.dbu
    
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            region_i = pya.Region([shapes[i]])
            region_j = pya.Region([shapes[j]])
            
            # Expand region_i and check for overlap with region_j
            expanded_i = region_i.sized(min_spacing)
            if expanded_i.overlaps(region_j):
                min_spacing_violations += 1
                print(f"  Shapes {i}-{j}: spacing violation")
    
    print(f"  Manual minimum spacing violations: {min_spacing_violations}")

def create_drc_markers(layout, errors):
    """Create marker layer for DRC errors"""
    if not errors:
        return
    
    top_cell = layout.cell("DRC_TEST")
    error_layer = layout.layer(100, 0)  # Error marker layer
    
    for error in errors:
        # Create a box around each error location
        bbox = error.shapes[0].bbox
        marker = pya.DBox(bbox.p1.x - 0.5, bbox.p1.y - 0.5,
                         bbox.p2.x + 0.5, bbox.p2.y + 0.5)
        top_cell.shapes(error_layer).insert(marker)

def main():
    """Main function"""
    layout = create_test_layout()
    
    # Run automatic DRC
    errors = run_drc_checks(layout)
    
    # Run manual DRC for comparison
    manual_drc_checks(layout)
    
    # Create error markers
    create_drc_markers(layout, errors)
    
    # Save layout with DRC markers
    layout.write("drc_test.gds")
    print(f"\nLayout saved to drc_test.gds")
    print(f"Error markers placed on layer 100/0")

if __name__ == "__main__":
    main()