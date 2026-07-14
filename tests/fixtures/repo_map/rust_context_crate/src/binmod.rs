// Owned by the binary crate only (declared solely by main.rs): its `crate::`
// import provably anchors at the BINARY root (main.rs), never the library
// sibling, and the bare `use helper::deep::...` resolves in the current scope
// because `mod helper;` is declared right here (edition 2021 uniform paths).
mod helper;

use crate::Item;
use helper::deep::Feature;

pub fn touch() -> (Item, Feature) {
    (Item, Feature)
}
