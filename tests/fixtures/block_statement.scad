// Test for brace-delimited block statements and variables with function calls

Width = max(10, 5);
Height = min(20, 30);

module myBox() {
  cube([Width, Height, 1]);
}

down(1) diff()
    cube([Width, Height, 2]) {
      if (Width > 5)
        attach(TOP)
          cube([Width/2, Height/2, 1]);
      if (Height > 10)
        attach(BOTTOM)
          cube([Width/2, Height/2, 1]);
    }
