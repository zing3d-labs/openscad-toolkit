/* [Basic Settings] */

// Width of the object
Width = 10;

// Material type
Material = "PLA"; // [PLA, PETG, ABS]

/* [Advanced] */

// Resolution
Resolution = 32; // [8:Low, 16:Medium, 32:High, 64:Ultra]

/* [Hidden] */
internal_size = Width * 2;

module customizerBox() {
  cube([Width, Width, internal_size]);
}

customizerBox();
