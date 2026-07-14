// Owned by the library crate only (declared solely by lib.rs), so `crate::`
// imports provably anchor at the LIBRARY root, and the inline module
// `inlined` resolves cross-file to lib.rs.
use crate::inlined::Cfg;
use crate::Item;

pub fn touch() -> (Cfg, Item) {
    (Cfg, Item)
}
