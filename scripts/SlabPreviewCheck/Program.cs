using System.Numerics;
using System.Text.Json.Nodes;
using Punctora.Desktop;

if(args.Length!=1)throw new ArgumentException("Pass a generated elements.json to check the native slab preview");
var model=JsonNode.Parse(File.ReadAllText(args[0]))!.AsObject();
var temporary=Path.Combine(Path.GetTempPath(),"punctora-slab-check-"+Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(Path.Combine(temporary,"assets"));
try
{
    File.WriteAllBytes(Path.Combine(temporary,"assets","preview.bin"),new byte[24]);
    var state=new JsonObject{["assets_directory"]="assets",["model"]=model,
        ["preview"]=new JsonObject{["path"]="preview.bin",["point_count"]=1,["source_point_count"]=1L}};
    var scene=SceneData.Load(Path.Combine(temporary,"check.punctora"),state);
    var checkedFaces=0;
    foreach(var slabNode in model["slabs"]!.AsArray())
    {
        var slab=slabNode!.AsObject();
        var element=scene.Elements.Single(e=>e.Id==slab["id"]!.GetValue<string>());
        var expected=slab["preview_geometry"]!["surface_triangles_xy"]!.AsArray();
        var top=(float)(slab["base"]!.GetValue<double>()+slab["thickness"]!.GetValue<double>());
        var area=0d;
        for(var i=0;i<element.Triangles.Length;i+=21)
        {
            var a=Camera.Position(element.Triangles,i);var b=Camera.Position(element.Triangles,i+7);var c=Camera.Position(element.Triangles,i+14);
            if(!float.IsFinite(a.X)||!float.IsFinite(b.Y)||!float.IsFinite(c.Z))throw new Exception("Nonfinite preview triangle");
            if(Math.Abs(a.Z-top)>1e-5||Math.Abs(b.Z-top)>1e-5||Math.Abs(c.Z-top)>1e-5)continue;
            area+=Math.Abs((b.X-a.X)*(c.Y-a.Y)-(b.Y-a.Y)*(c.X-a.X))/2;
            checkedFaces++;
        }
        var expectedArea=0d;
        foreach(var triangle in expected)
        {
            Vector2 Point(int i)=>new((float)triangle![i]![0]!.GetValue<double>(),(float)triangle![i]![1]!.GetValue<double>());
            var a=Point(0);var b=Point(1);var c=Point(2);
            expectedArea+=Math.Abs((b.X-a.X)*(c.Y-a.Y)-(b.Y-a.Y)*(c.X-a.X))/2;
        }
        if(Math.Abs(area-expectedArea)>Math.Max(.001,expectedArea*.001))throw new Exception("Desktop slab cap differs from void-cut mesh");
    }
    Console.WriteLine($"Native preview verified: {model["slabs"]!.AsArray().Count} slabs, {checkedFaces} void-cut cap triangles");
}
finally
{
    // Only this process's unique temporary fixture is removed.
    Directory.Delete(temporary,true);
}
