// Binary crate root, sharing src/ with lib.rs. Declares its own module tree
// plus the same shared module the library root declares.
mod binmod;
mod shared;

pub struct Item;

fn main() {}
