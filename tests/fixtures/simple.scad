// Simple test file with variables and a module

/* [Basic Settings] */

// Width of the box
Width = 10;

// Height of the box
Height = 20;

/* [Hidden] */
internal_val = 5;

module simpleBox() {
  cube([Width, Height, internal_val]);
}

simpleBox();
