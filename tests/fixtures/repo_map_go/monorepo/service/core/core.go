package core

// Run belongs to the nested module rooted at service/go.mod; the importer
// service/cmd/run.go must resolve example.com/service/core against THAT module,
// never the outer example.com/root module.
func Run() {}
