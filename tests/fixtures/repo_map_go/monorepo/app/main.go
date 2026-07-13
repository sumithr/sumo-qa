package main

import (
	"fmt"

	"example.com/root/lib/util"
	"github.com/ext/widget"
)

func main() {
	fmt.Println(util.Parse(), util.Format(), widget.Name)
}
