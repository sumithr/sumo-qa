// Crate root (binary). Declares the top-level modules and reaches one of them
// via an absolute `crate::` path. `std` is external and must be dropped.
mod foo;
mod bar;

use crate::foo::Thing;
use std::collections::HashMap;

fn main() {
    let _t = Thing::new();
    let _m: HashMap<u8, u8> = HashMap::new();
}
