use <nonexistent_library/tool.scad>

Size = 42;

module missingUseUser() { cube(Size); }

missingUseUser();
