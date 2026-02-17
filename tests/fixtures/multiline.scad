/*
 * Multi-line block comment at the top.
 * This should be preserved in output.
 */

// Multi-line list assignment
Colors = [
  "red",
  "green",
  "blue"
];

Size = 5;

module multilineBox(
  width,
  height,
  depth) {
  cube([width, height, depth]);
}

multilineBox(
  Size,
  Size * 2,
  Size * 3
);
