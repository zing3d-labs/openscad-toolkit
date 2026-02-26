condition1 = true;
condition2 = true;
/* [Hidden] */
$fn = 100;
empty = [
  if (condition1) "content1",
  if (condition2) "content2",
];
never_empty = [
  !condition1 ? "" : "content1",
  !condition2 ? "" : "content2",
];
if (len(empty) == 0)
  translate([0, 10, 0]) linear_extrude(2) text("shown when empty");
if (len(never_empty) == 0)
  translate([0, -10, 0]) linear_extrude(2) text("never shown");
