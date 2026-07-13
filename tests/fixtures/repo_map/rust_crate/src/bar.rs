// Module `bar`. Reaches `foo` via an absolute `crate::` path, so this file
// depends on `foo.rs`.
use crate::foo::Thing;

#[derive(Default)]
pub struct Bar;

impl Bar {
    pub fn make() -> Thing {
        Thing
    }
}
