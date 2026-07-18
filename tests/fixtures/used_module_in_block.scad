// A module file that wraps its demo call and module definition in a bare
// { } block, matching a real-world pattern used to hide helper variables
// from the Customizer while a standalone demo call still renders when this
// file is opened directly (not `use`'d).
someVar = 42;

{
  helperSize = someVar * 2;

  usedHelper(helperSize);

  module usedHelper(size) {
    sphere(r=size);
  }
}
