// A single-file Cargo example target: its own crate root. `mod exhelper;`
// resolves beside the root file (rustc reads a crate root's mod files from
// its own containing directory), and the bare `use exhelper::Ex` resolves in
// the current scope because the declaration is local to this root.
mod exhelper;

use exhelper::Ex;

fn main() {
    let _e = Ex;
}
