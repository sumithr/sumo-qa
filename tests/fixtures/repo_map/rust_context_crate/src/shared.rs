// Declared by BOTH crate roots (`mod shared;` in lib.rs and main.rs), so its
// crate membership is ambiguous: `use crate::Item` must NOT guess an edge to
// either root, and the undeclared bare head must stay external even though a
// file with the matching name exists in src/.
use crate::Item;
use extern_dep::Thing;

pub fn touch() -> Item {
    Item
}
