// Library crate root of a mixed lib+bin package. Declares the lib-only module
// tree, an inline module (reached cross-file via `crate::inlined::...`), and
// the shared module that the binary root also declares (ambiguous membership).
mod libmod;
mod shared;

pub mod inlined {
    pub struct Cfg;
}

pub struct Item;
