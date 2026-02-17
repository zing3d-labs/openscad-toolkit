// A file referenced via include<> — has var + module

includedVar = 100;

module includedModule() {
  cylinder(h=includedVar, r=5);
}
