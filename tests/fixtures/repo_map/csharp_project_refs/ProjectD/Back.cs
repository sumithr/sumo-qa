using ProjectC.App;

namespace ProjectD;

public class Back
{
    // ProjectD does NOT reference ProjectC, so this cross-project `using` is a
    // true negative even though ProjectC declares ProjectC.App.
}
