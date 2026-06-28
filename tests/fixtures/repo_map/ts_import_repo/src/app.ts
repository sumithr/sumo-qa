import { greet } from "./util";
import { Btn } from "./components";
import _ from "lodash";

void greet;
void Btn;
void _;

export function lazyConfig() {
  const m = require("./config");
  return m.cfg;
}
