use <used_with_shared_var.scad>

// Entry file redefines a variable that also exists in the use'd file.
// After compilation, SharedVar = 5 must appear at the top level.
SharedVar = 5;
EntryOnly = 10;

libModule(SharedVar);
