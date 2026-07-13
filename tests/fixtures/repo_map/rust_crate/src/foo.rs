// Module `foo` (a non-mod, non-root file, so its children live in `foo/`).
// Declares a child module and reaches a sibling module via `super::`.
mod helper;

use self::helper::Helper;
use super::bar::Bar;

pub struct Thing;

impl Thing {
    pub fn new() -> Self {
        let _h = Helper::default();
        let _b = Bar::default();
        Thing
    }
}
