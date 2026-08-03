using ProjectD.Models;
using ProjectF.Widgets;

namespace ProjectC.App;

public class Consumer
{
    // ProjectD.Models resolves (ProjectC references ProjectD); ProjectF.Widgets
    // does not (ProjectF is unreferenced).
    public Thing Item = new Thing();
    public Gadget Panel = new Gadget();
}
