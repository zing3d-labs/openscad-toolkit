include <nonexistent_library/defs.scad>

Size = 42;

module missingIncludeUser() { cube(Size); }

missingIncludeUser();
