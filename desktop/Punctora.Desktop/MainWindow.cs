using System.Globalization;
using System.Diagnostics;
using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Selection;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform.Storage;
using Avalonia.Threading;

namespace Punctora.Desktop;

public sealed class MainWindow : Window
{
    readonly WorkerClient worker=new();
    readonly SceneViewport viewport;
    readonly TextBlock status=Text("Open a project, import an E57 or try the example.",12);
    readonly TextBlock backend=Text("Initializing graphics",11);
    readonly TextBlock projectTitle=Text("No project open",18);
    readonly TextBlock counts=Text("",11);
    readonly TextBlock warnings=Text("Review candidates against the scan before accepting geometry.",12);
    readonly TextBlock evidence=Text("Select a wall, slab or storey to review its parameters.",12);
    readonly TextBlock selectedTitle=Text("Element properties",17);
    readonly StackPanel fieldsPanel=new(){Spacing=8};
    readonly Dictionary<string,TextBox> fields=[];
    readonly Dictionary<string,string> initialFields=[];
    readonly ListBox elements=new(){SelectionMode=SelectionMode.Multiple};
    readonly ComboBox storeys=new(){HorizontalAlignment=HorizontalAlignment.Stretch};
    readonly ComboBox method=new(){ItemsSource=new[]{"Contours","Region growing"},SelectedIndex=0};
    readonly ComboBox review=new(){ItemsSource=new[]{"unreviewed","reviewed","flagged","rejected"},SelectedIndex=0,HorizontalAlignment=HorizontalAlignment.Stretch};
    readonly ComboBox classification=new(){ItemsSource=new[]{"unclassified","paired_faces","single_face_candidate","exterior_candidate","consolidated_candidate","interior","exterior"},SelectedIndex=0,HorizontalAlignment=HorizontalAlignment.Stretch};
    readonly CheckBox zUp=new(){Content="Z is up (confirm before fitting)"};
    readonly Slider section=new(){Minimum=0,Maximum=10,Value=10};
    readonly ProgressBar progress=new(){Minimum=0,Maximum=100,Height=4};
    readonly List<Button> projectActions=[];
    readonly Button save,apply,cancel,undoButton,mergeButton,splitButton;
    readonly TextBox splitOffset=new(){Watermark="Distance from wall start (m)"};
    readonly Stack<JsonNode> undo=[];
    CancellationTokenSource? jobCancellation;
    JsonObject? state;
    string? projectPath,selectedId;
    bool busy,dirty,refreshing;
    string[] elementIds=[];

    public MainWindow(string[] args)
    {
        Title="Punctora BIM Studio | 0.3.0a4 desktop preview";Width=1440;Height=920;MinWidth=1080;MinHeight=700;
        Background=Brush.Parse("#0B1220");
        viewport=new SceneViewport(args.Contains("--software")||Environment.GetEnvironmentVariable("PUNCTORA_SOFTWARE_PREVIEW")=="1");
        viewport.BackendChanged=value=>backend.Text=value;
        viewport.ElementSelected=id=>{selectedId=id;var index=Array.IndexOf(elementIds,id);elements.SelectedIndex=index;ShowProperties();viewport.View.Selected=id;viewport.Redraw();};
        var root=new Grid{RowDefinitions=new RowDefinitions("Auto,Auto,*,Auto"),Margin=new Thickness(18,14)};
        var header=new Grid{ColumnDefinitions=new ColumnDefinitions("Auto,*,Auto"),Margin=new Thickness(0,0,0,14)};
        var brand=new StackPanel{Spacing=3};brand.Children.Add(Text("PUNCTORA  /  BIM STUDIO",20));brand.Children.Add(Text("Point clouds to reviewed IFC",11));
        header.Children.Add(brand);Grid.SetColumn(projectTitle,1);projectTitle.Margin=new Thickness(35,0,12,0);header.Children.Add(projectTitle);
        var alpha=Text("M3 PREVIEW 0.3.0a4",11);alpha.Foreground=Brush.Parse("#FBBF24");Grid.SetColumn(alpha,2);header.Children.Add(alpha);root.Children.Add(header);
        var toolbar=new StackPanel{Orientation=Orientation.Horizontal,Spacing=8,Margin=new Thickness(0,0,0,14)};
        Button Action(string label,Func<Task> action){var button=Button(label,async()=>await Guard(action));toolbar.Children.Add(button);projectActions.Add(button);return button;}
        Action("Import E57",ImportAsync);Action("Example",DemoAsync);Action("Open",OpenAsync);
        save=Action("Save",SaveAsync);Action("Save copy",CopyAsync);Action("Detect elements",ReconstructAsync);Action("Convert to IFC",ExportAsync);
        undoButton=Action("Undo edit",UndoAsync);Action("Revert",RevertAsync);
        cancel=Button("Cancel job",()=>{jobCancellation?.Cancel();return Task.CompletedTask;});cancel.IsEnabled=false;toolbar.Children.Add(cancel);
        Grid.SetRow(toolbar,1);root.Children.Add(toolbar);
        var body=new Grid{ColumnDefinitions=new ColumnDefinitions("240,12,*,12,295")};Grid.SetRow(body,2);root.Children.Add(body);
        var left=new Grid{RowDefinitions=new RowDefinitions("Auto,*"),Margin=new Thickness(12)};
        var options=new StackPanel{Spacing=9};options.Children.Add(Text("VIEW & ELEMENT DETECTION",12));options.Children.Add(storeys);
        var cloud=new CheckBox{Content="Point cloud",IsChecked=true};var model=new CheckBox{Content="Model candidates",IsChecked=true};
        cloud.IsCheckedChanged+=(_,_)=>{viewport.View.Cloud=cloud.IsChecked==true;viewport.Redraw();};
        model.IsCheckedChanged+=(_,_)=>{viewport.View.Model=model.IsChecked==true;viewport.Redraw();};options.Children.Add(cloud);options.Children.Add(model);
        options.Children.Add(Button("Fit view",()=>{viewport.View.Camera.Fit(viewport.View.Scene);viewport.Redraw();return Task.CompletedTask;}));
        options.Children.Add(Text("Model opacity",11));var opacity=new Slider{Minimum=.05,Maximum=1,Value=1};opacity.PropertyChanged+=(_,e)=>{if(e.Property==Slider.ValueProperty){viewport.View.Opacity=(float)opacity.Value;viewport.Redraw();}};options.Children.Add(opacity);
        options.Children.Add(Text("Section: visible below height",11));options.Children.Add(section);
        section.PropertyChanged+=(_,e)=>{if(e.Property==Slider.ValueProperty)FilterStorey();};
        options.Children.Add(Text("Surface method",11));options.Children.Add(method);options.Children.Add(zUp);
        var software=new CheckBox{Content="Use software preview",IsChecked=viewport.SoftwareMode};
        software.IsCheckedChanged+=(_,_)=>{if(software.IsChecked==true)viewport.UseSoftware("Selected in settings");else viewport.UseAutomatic();};options.Children.Add(software);
        options.Children.Add(Text("ELEMENTS",12));left.Children.Add(options);Grid.SetRow(elements,1);elements.Margin=new Thickness(0,8,0,0);left.Children.Add(elements);
        body.Children.Add(Panel(left));
        var center=new Grid{RowDefinitions=new RowDefinitions("*,Auto")};Grid.SetColumn(center,2);body.Children.Add(center);
        center.Children.Add(new Border{Child=viewport,CornerRadius=new CornerRadius(10),ClipToBounds=true});
        var viewFooter=new StackPanel{Spacing=4,Margin=new Thickness(8,8,8,0)};viewFooter.Children.Add(counts);viewFooter.Children.Add(Text("Drag: orbit  ·  Right-drag: pan  ·  Wheel: zoom  ·  Click model: select",11));viewFooter.Children.Add(backend);Grid.SetRow(viewFooter,1);center.Children.Add(viewFooter);
        var inspector=new StackPanel{Spacing=10,Margin=new Thickness(14)};inspector.Children.Add(selectedTitle);inspector.Children.Add(fieldsPanel);inspector.Children.Add(Text("Review state",11));inspector.Children.Add(review);inspector.Children.Add(Text("Wall classification",11));inspector.Children.Add(classification);
        apply=Button("Apply correction",ApplyAsync);inspector.Children.Add(apply);
        inspector.Children.Add(Text("WALL TOPOLOGY",11));
        mergeButton=Button("Merge selected wall fragments",()=>MergeWallsAsync());inspector.Children.Add(mergeButton);
        inspector.Children.Add(splitOffset);splitButton=Button("Split selected wall",SplitWallAsync);inspector.Children.Add(splitButton);
        inspector.Children.Add(Text("Ctrl-click wall rows to select fragments for merging. Split distance is measured from the selected wall start.",11));
        inspector.Children.Add(Text("SCAN EVIDENCE & ASSUMPTIONS",11));inspector.Children.Add(evidence);inspector.Children.Add(Text("PROJECT FINDINGS",11));inspector.Children.Add(warnings);
        var right=Panel(new ScrollViewer{Content=inspector,HorizontalScrollBarVisibility=Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled});Grid.SetColumn(right,4);body.Children.Add(right);
        // Keep the descriptive status above the thin progress strip. On short
        // displays the final row can be clipped at the bottom; job failures
        // must remain visible and screenshot-readable.
        var footer=new StackPanel{Spacing=7,Margin=new Thickness(0,12,0,0)};footer.Children.Add(status);footer.Children.Add(progress);Grid.SetRow(footer,3);root.Children.Add(footer);Content=root;
        storeys.SelectionChanged+=(_,_)=>FilterStorey();
        elements.SelectionChanged+=(_,_)=>{if(refreshing)return;selectedId=elements.SelectedIndex>=0?elementIds[elements.SelectedIndex]:null;viewport.View.Selected=selectedId;ShowProperties();viewport.Redraw();};
        Closing+=(_,e)=>
        {
            if(dirty){e.Cancel=true;status.Text="Save or revert your corrections before closing the project.";}
            else jobCancellation?.Cancel();
        };
        Opened+=async(_,_)=>
        {
            if(args.Contains("--verify-ui"))await VerifyUiAsync(args);
            else if(args.Contains("--verify-preview"))await VerifyPreviewAsync(args);
            else if(args.FirstOrDefault(a=>a.EndsWith(".punctora",StringComparison.OrdinalIgnoreCase)) is { } path)await Guard(()=>LoadAsync(path));
        };
        UpdateActions();
    }
    static TextBlock Text(string text,double size)=>new(){Text=text,FontSize=size,TextWrapping=TextWrapping.Wrap,Foreground=Brush.Parse("#CBD5E1")};
    static Border Panel(Control child)=>new(){Child=child,Background=Brush.Parse("#141E30"),CornerRadius=new CornerRadius(10)};
    static Button Button(string label,Func<Task> action)
    {var button=new Button{Content=label,Padding=new Thickness(12,8),HorizontalAlignment=HorizontalAlignment.Stretch};button.Click+=async(_,_)=>await action();return button;}
    async Task Guard(Func<Task> action){try{await action();}catch(Exception e){status.Text=e.Message;}}
    void UpdateActions()
    {
        foreach(var button in projectActions)button.IsEnabled=!busy;
        cancel.IsEnabled=busy;apply.IsEnabled=!busy&&selectedId!=null;save.IsEnabled=!busy&&dirty&&state?["model"]!=null;undoButton.IsEnabled=!busy&&undo.Count>0;
        var selectedWalls=SelectedWallIds();var selected=Selected();mergeButton.IsEnabled=!busy&&selectedWalls.Length>=2;splitButton.IsEnabled=!busy&&selected!=null&&selected.Value.Kind=="walls";splitOffset.IsEnabled=splitButton.IsEnabled;
        method.IsEnabled=zUp.IsEnabled=!busy;
        foreach(var field in fields.Values)field.IsEnabled=!busy;
        review.IsEnabled=classification.IsEnabled=!busy&&selectedId!=null;
        projectTitle.Text=state==null?"No project open":state["name"]!.GetValue<string>()+(dirty?"  * unsaved corrections":"");
    }
    bool RequireClean(){if(!dirty)return true;status.Text="Save or revert your corrections before opening or reconstructing another project.";return false;}
    async Task<JsonObject?> RunAsync(string command,string path,JsonObject? extra=null)
    {
        if(busy)return null;
        busy=true;jobCancellation=new();UpdateActions();progress.Value=0;progress.IsIndeterminate=true;
        var request=extra??new JsonObject();request["command"]=command;request["project"]=path;
        try
        {
            var result=await worker.RunAsync(request,(value,phase)=>Dispatcher.UIThread.Post(()=>{progress.IsIndeterminate=false;progress.Value=value;status.Text=phase+" · conversion: CPU";}),jobCancellation.Token);
            status.Text="Completed";progress.Value=100;return result;
        }
        catch(OperationCanceledException)
        {
            status.Text="Job stopped. Saved work is preserved.";
            if(File.Exists(path))
            {
                // A completed atomic save may have raced cancellation; reopen its authoritative state.
                var reopened=await worker.RunAsync(new JsonObject{["command"]="open",["project"]=path},null,CancellationToken.None);
                // Keep unsaved corrections unless an atomic write actually advanced the saved revision.
                if(projectPath!=path||state?["revision"]?.ToJsonString()!=reopened["revision"]?.ToJsonString())
                {dirty=false;undo.Clear();await PresentAsync(path,reopened,true);}
                await worker.RunAsync(new JsonObject{["command"]="cleanup",["project"]=path},null,CancellationToken.None);
            }
            return null;
        }
        catch(Exception e){status.Text="Job failed: "+e.Message;return null;}
        finally{busy=false;progress.IsIndeterminate=false;jobCancellation.Dispose();jobCancellation=null;UpdateActions();}
    }
    JsonObject ModelRequest()=>new(){["expected_revision"]=state!["revision"]!.DeepClone(),["model"]=state["model"]?.DeepClone()};
    async Task PresentAsync(string path,JsonObject value,bool fit)
    {
        var scene=await Task.Run(()=>SceneData.Load(path,value));
        state=value;projectPath=path;viewport.SetScene(scene,fit);refreshing=true;
        try
        {
            var priorStorey=viewport.View.Storey;
            var model=state["model"] as JsonObject;
            var levels=model?["storeys"]?.AsArray()??[];
            storeys.ItemsSource=new[]{"All storeys"}.Concat(levels.Select(s=>s!["name"]!.GetValue<string>())).ToArray();
            storeys.SelectedIndex=priorStorey==null?0:Math.Max(0,levels.ToList().FindIndex(s=>s!["id"]!.GetValue<string>()==priorStorey)+1);
            var nodes=model==null?new List<(string Kind,JsonObject Node)>():new[]{"storeys","walls","slabs","openings","stairs"}.SelectMany(kind=>(model[kind]?.AsArray()??[]).Select(n=>(Kind:kind,Node:n!.AsObject()))).ToList();
            elementIds=nodes.Select(n=>n.Node["id"]!.GetValue<string>()).ToArray();
            elements.ItemsSource=nodes.Select(n=>$"{n.Kind} · {n.Node["id"]}\n{n.Node["review_state"]?.GetValue<string>()??"levels / inferred outline"}").ToArray();
            elements.SelectedIndex=Array.IndexOf(elementIds,selectedId);
            zUp.IsChecked=state["coordinate_confirmation"]!["z_up"]!.GetValue<bool>();
            section.Minimum=scene.Minimum.Z-.5;section.Maximum=scene.Maximum.Z+.5;
            if(fit)section.Value=section.Maximum;else section.Value=Math.Clamp(section.Value,section.Minimum,section.Maximum);
            warnings.Text=string.Join("\n\n",state["warnings"]!.AsArray().Select(n=>n!.GetValue<string>()).Concat(model?["warnings"]?.AsArray().Select(n=>n!.GetValue<string>())??[]).Distinct());
            counts.Text=$"Preview: {scene.Points.Length/7:N0} of {scene.TotalPoints:N0} points · {model?["walls"]?.AsArray().Count??0} walls, {model?["slabs"]?.AsArray().Count??0} slabs, {model?["openings"]?.AsArray().Count??0} openings, {model?["stairs"]?.AsArray().Count??0} stairs · local metres";
        }
        finally{refreshing=false;}
        ShowProperties();FilterStorey();UpdateActions();
    }
    void FilterStorey()
    {
        if(refreshing||state==null)return;
        var levels=(state["model"] as JsonObject)?["storeys"]?.AsArray();
        if(storeys.SelectedIndex>0&&levels!=null)
        {
            var level=levels[storeys.SelectedIndex-1]!;viewport.View.Storey=level["id"]!.GetValue<string>();
            viewport.View.ZMin=(float)(level["elevation"]!.GetValue<double>()-.6);
            viewport.View.ZMax=Math.Min((float)section.Value,(float)(level["ceiling"]!.GetValue<double>()+.6));
        }
        else{viewport.View.Storey=null;viewport.View.ZMin=-1e20f;viewport.View.ZMax=(float)section.Value;}
        viewport.Redraw();
    }
    (string Kind,JsonObject Node)? Selected()
    {
        if(state?["model"] is not JsonObject model||selectedId==null)return null;
        foreach(var kind in new[]{"storeys","walls","slabs","openings","stairs"})
            foreach(var node in model[kind]?.AsArray()??[])if(node!["id"]!.GetValue<string>()==selectedId)return(kind,node.AsObject());
        return null;
    }
    string[] SelectedWallIds()
    {
        if(state?["model"] is not JsonObject model)return [];
        var walls=(model["walls"]?.AsArray()??[]).Select(node=>node!["id"]!.GetValue<string>()).ToHashSet();
        return elements.Selection.SelectedIndexes.Where(index=>index>=0&&index<elementIds.Length).Select(index=>elementIds[index]).Where(walls.Contains).Distinct().ToArray();
    }
    void ShowProperties()
    {
        fields.Clear();initialFields.Clear();fieldsPanel.Children.Clear();var selection=Selected();
        if(selection==null){selectedTitle.Text="Element properties";evidence.Text="Select a wall, slab, opening, stair or storey.";UpdateActions();return;}
        var (kind,obj)=selection.Value;selectedTitle.Text=obj["id"]!.GetValue<string>();
        void Field(string key,string label,string value)
        {
            fieldsPanel.Children.Add(Text(label,11));var box=new TextBox{Text=value,Name="Edit_"+key};fields[key]=box;initialFields[key]=value;fieldsPanel.Children.Add(box);
        }
        void Number(string key,string label)=>Field(key,label,obj[key]!.GetValue<double>().ToString("G10",CultureInfo.InvariantCulture));
        if(kind=="walls")
        {
            for(var j=0;j<2;j++)foreach(var key in new[]{"start","end"})Field(key+j,key+" "+(j==0?"X":"Y")+" (m)",obj[key]![j]!.GetValue<double>().ToString("G10",CultureInfo.InvariantCulture));
            Number("base","Base (m)");Number("height","Height (m)");Number("thickness","Thickness (m)");
            var dx=obj["end"]![0]!.GetValue<double>()-obj["start"]![0]!.GetValue<double>();var dy=obj["end"]![1]!.GetValue<double>()-obj["start"]![1]!.GetValue<double>();
            splitOffset.Text=(Math.Sqrt(dx*dx+dy*dy)/2).ToString("G10",CultureInfo.InvariantCulture);
        }
        else if(kind=="slabs"){Number("base","Base (m)");Number("thickness","Thickness (m)");}
        else if(kind=="openings")
        {
            Field("kind","Kind (door / window)",obj["kind"]!.GetValue<string>());
            foreach(var key in new[]{"offset","sill","width","height"})Number(key,key+" (m)");
        }
        else if(kind=="stairs")
        {
            for(var j=0;j<2;j++)foreach(var key in new[]{"start","end"})Field(key+j,key+" "+(j==0?"X":"Y")+" (m)",obj[key]![j]!.GetValue<double>().ToString("G10",CultureInfo.InvariantCulture));
            foreach(var key in new[]{"base","width","rise","going","tread_thickness"})Number(key,key+" (m)");
            Field("steps","Number of treads",obj["steps"]!.GetValue<int>().ToString(CultureInfo.InvariantCulture));
        }
        else{Field("name","Storey name",obj["name"]!.GetValue<string>());Number("elevation","Floor level (m)");Number("ceiling","Ceiling level (m)");}
        review.SelectedItem=obj["review_state"]?.GetValue<string>()??"unreviewed";review.IsVisible=kind!="storeys";
        classification.SelectedItem=obj["classification"]?.GetValue<string>()??"unclassified";classification.IsVisible=kind=="walls";
        var provenance=obj["provenance"]?.AsObject().Select(p=>$"{p.Key}: {p.Value}")??[];
        evidence.Text=(kind=="walls"?$"Supporting original points: {obj["evidence_count"]}\nObserved-face fit RMSE: {obj["fit_rmse_m"]?.ToJsonString()??"unknown"} m\n\n":"")+string.Join("\n",provenance)+"\n\nObserved faces and fit statistics refer to the original fit. Corrections are recorded as user supplied.";
        if(kind=="openings"||kind=="stairs")evidence.Text=$"Geometric support score: {obj["confidence"]?.ToJsonString()??"unknown"} (not an accuracy probability)\n{obj["evidence"]?["scope"]?.GetValue<string>()??"Caller-supplied geometry"}\n\n"+evidence.Text;
        UpdateActions();
    }
    static double Parse(string text)
    {
        if((double.TryParse(text,NumberStyles.Float,CultureInfo.InvariantCulture,out var value)||double.TryParse(text,NumberStyles.Float,CultureInfo.CurrentCulture,out value))&&double.IsFinite(value))return value;
        throw new InvalidOperationException("Enter a finite number in metres.");
    }
    async Task ApplyAsync()=>await Guard(async()=>
    {
        var selection=Selected();if(selection==null||state==null||projectPath==null||busy)return;
        var (kind,obj)=selection.Value;var changes=new JsonObject();
        foreach(var (key,box) in fields)
        {
            if(box.Text==initialFields[key])continue;
            if(key.StartsWith("start")||key.StartsWith("end"))continue;
            JsonNode value=key=="name"||key=="kind"?JsonValue.Create(box.Text?.Trim()??"")!:key=="steps"?JsonValue.Create(int.Parse(box.Text??"",CultureInfo.InvariantCulture))!:JsonValue.Create(Parse(box.Text??""))!;
            if(value.ToJsonString()!=obj[key]!.ToJsonString())changes[key]=value;
        }
        if(kind=="walls"||kind=="stairs")foreach(var key in new[]{"start","end"})
        {
            if(fields[key+0].Text==initialFields[key+0]&&fields[key+1].Text==initialFields[key+1])continue;
            var array=new JsonArray(Enumerable.Range(0,2).Select(j=>fields[key+j].Text==initialFields[key+j]?obj[key]![j]!.DeepClone():JsonValue.Create(Parse(fields[key+j].Text??""))).ToArray());
            if(array.ToJsonString()!=obj[key]!.ToJsonString())changes[key]=array;
        }
        if(kind!="storeys"&&review.SelectedItem is string r&&r!=obj["review_state"]!.GetValue<string>())changes["review_state"]=r;
        if(kind=="walls"&&classification.SelectedItem is string c&&c!=obj["classification"]!.GetValue<string>())changes["classification"]=c;
        if(changes.Count==0){status.Text="No parameters changed.";return;}
        var previous=state["model"]!.DeepClone();var request=ModelRequest();request["element_id"]=selectedId;request["changes"]=changes;
        var result=await RunAsync("edit",projectPath,request);
        if(result==null)return;
        undo.Push(previous);dirty=true;await PresentAsync(projectPath,result,false);status.Text="Correction applied. Save to keep it.";
    });
    async Task UndoAsync()
    {if(state==null||projectPath==null||undo.Count==0)return;state["model"]=undo.Pop();dirty=true;await PresentAsync(projectPath,state,false);status.Text="Edit undone. Save to keep this version.";}
    async Task RevertAsync(){if(projectPath==null)return;dirty=false;undo.Clear();await LoadAsync(projectPath);}
    async Task MergeWallsAsync(string[]? requested=null)
    {
        if(state==null||projectPath==null||busy)return;var ids=requested??SelectedWallIds();
        if(ids.Length<2){status.Text="Ctrl-click at least two collinear wall rows to merge.";return;}
        var previous=state["model"]!.DeepClone();var request=ModelRequest();request["wall_ids"]=new JsonArray(ids.Select(id=>(JsonNode?)JsonValue.Create(id)).ToArray());
        var result=await RunAsync("merge_walls",projectPath,request);if(result==null)return;
        undo.Push(previous);dirty=true;selectedId=ids[0];await PresentAsync(projectPath,result,false);status.Text=$"Merged {ids.Length} wall fragments. Save to keep this version.";
    }
    async Task SplitWallAsync()
    {
        var selection=Selected();if(state==null||projectPath==null||busy||selection==null||selection.Value.Kind!="walls")return;
        var previous=state["model"]!.DeepClone();var request=ModelRequest();request["wall_id"]=selection.Value.Node["id"]!.GetValue<string>();request["offset"]=Parse(splitOffset.Text??"");
        var result=await RunAsync("split_wall",projectPath,request);if(result==null)return;
        undo.Push(previous);dirty=true;selectedId=selection.Value.Node["id"]!.GetValue<string>();await PresentAsync(projectPath,result,false);status.Text="Wall split and hosted openings reassigned. Save to keep this version.";
    }
    async Task<string?> PickProjectAsync(string title)
    {
        var file=await StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions{Title=title,SuggestedFileName="Punctora-project.punctora",DefaultExtension="punctora",FileTypeChoices=[new FilePickerFileType("Punctora project"){Patterns=["*.punctora"]}]});
        return file?.TryGetLocalPath();
    }
    async Task DemoAsync()
    {if(!RequireClean())return;var path=await PickProjectAsync("Create example project");if(path==null)return;var result=await RunAsync("demo",path,new JsonObject{["two_storeys"]=true});if(result!=null){dirty=false;undo.Clear();await PresentAsync(path,result,true);}}
    async Task ImportAsync()
    {
        if(!RequireClean())return;
        var files=await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions{Title="Choose a registered E57",AllowMultiple=false,FileTypeFilter=[new FilePickerFileType("E57 scan"){Patterns=["*.e57"]}]});
        var input=files.FirstOrDefault()?.TryGetLocalPath();if(input==null)return;var path=await PickProjectAsync("Save imported scan as a new project");if(path==null)return;
        var result=await RunAsync("import",path,new JsonObject{["input"]=input});if(result!=null){dirty=false;undo.Clear();await PresentAsync(path,result,true);}
    }
    async Task OpenAsync()
    {
        if(!RequireClean())return;
        var files=await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions{Title="Open project",AllowMultiple=false,FileTypeFilter=[new FilePickerFileType("Punctora project"){Patterns=["*.punctora"]}]});
        if(files.FirstOrDefault()?.TryGetLocalPath() is { } path)await LoadAsync(path);
    }
    async Task LoadAsync(string path)
    {var result=await RunAsync("open",path);if(result!=null){dirty=false;undo.Clear();await PresentAsync(path,result,true);await RunAsync("cleanup",path);}}
    async Task SaveAsync()
    {if(state==null||projectPath==null||state["model"]==null)return;var result=await RunAsync("save",projectPath,ModelRequest());if(result!=null){dirty=false;await PresentAsync(projectPath,result,false);status.Text="Project saved.";}}
    async Task CopyAsync()
    {
        if(state==null||projectPath==null)return;var destination=await PickProjectAsync("Save project and its data as a new copy");if(destination==null)return;
        var request=ModelRequest();request["destination"]=destination;var result=await RunAsync("save_copy",projectPath,request);if(result!=null){dirty=false;undo.Clear();await PresentAsync(destination,result,false);status.Text="Project copy saved. Keep its assets folder with the project file.";}
    }
    async Task ReconstructAsync()
    {
        if(state==null||projectPath==null||!RequireClean())return;
        if(zUp.IsChecked!=true){status.Text="Confirm Z is up before fitting. A missing CRS can remain explicitly unknown for local review.";return;}
        var request=new JsonObject{["expected_revision"]=state["revision"]!.DeepClone(),["confirm_z_up"]=true,["settings"]=new JsonObject{["surface_method"]=method.SelectedIndex==1?"region_growing":"contour"}};
        var result=await RunAsync("reconstruct",projectPath,request);if(result!=null){dirty=false;undo.Clear();await PresentAsync(projectPath,result,false);await RunAsync("cleanup",projectPath);}
    }
    async Task ExportAsync()
    {
        if(state==null||projectPath==null)return;
        if(state["model"]==null){await ReconstructAsync();if(state?["model"]==null)return;}
        var file=await StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions{Title="Export reviewed IFC4",SuggestedFileName=state["name"]!.GetValue<string>()+".ifc",DefaultExtension="ifc",FileTypeChoices=[new FilePickerFileType("IFC4 model"){Patterns=["*.ifc"]}]});
        if(file?.TryGetLocalPath() is { } path)await ExportToAsync(path);
    }
    async Task ExportToAsync(string path)
    {
        var request=ModelRequest();request["output"]=path;var result=await RunAsync("export",projectPath!,request);
        if(result!=null){status.Text="IFC4 exported and validated. This does not establish survey accuracy.";warnings.Text=string.Join("\n\n",result["warnings"]!.AsArray().Select(n=>n!.GetValue<string>()));}
    }
    async Task VerifyUiAsync(string[] args)
    {
        var output=Path.GetFullPath(args[Array.IndexOf(args,"--verify-ui")+1]);Directory.CreateDirectory(output);
        try
        {
            var path=Path.Combine(output,"walkthrough.punctora");var result=await RunAsync("demo",path,new JsonObject{["two_storeys"]=true});if(result==null)throw new Exception(status.Text);
            await PresentAsync(path,result,true);
            var sample=state!["model"]!["walls"]![0]!;
            // Explicit synthetic candidates exercise new preview/edit/save/IFC
            // plumbing independently of the detector's geometry regressions.
            var opening=new JsonObject{["id"]="ui-window",["host_wall_id"]=sample["id"]!.DeepClone(),["kind"]="window",["offset"]=.2,["sill"]=.8,["width"]=.6,["height"]=.8,["provenance"]=new JsonObject{["dimensions"]="user_supplied"},["review_state"]="unreviewed"};
            state["model"]!["openings"]!.AsArray().Add(opening);
            var sx=sample["start"]![0]!.GetValue<double>();var sy=sample["start"]![1]!.GetValue<double>();
            state["model"]!["stairs"]!.AsArray().Add(new JsonObject{["id"]="ui-stair",["storey_id"]=sample["storey_id"]!.DeepClone(),["start"]=new JsonArray(sx,sy),["end"]=new JsonArray(sx+2,sy),["base"]=sample["base"]!.DeepClone(),["width"]=.9,["rise"]=.17,["going"]=.25,["steps"]=8,["tread_thickness"]=.06,["provenance"]=new JsonObject{["treads"]="user_supplied"},["review_state"]="unreviewed"});
            await PresentAsync(path,state,false);
            if(!viewport.View.Scene.Elements.Any(e=>e.Kind=="window")||!viewport.View.Scene.Elements.Any(e=>e.Kind=="Stair"))throw new Exception("Feature preview missing");
            var target=new System.Numerics.Vector3((float)((sample["start"]![0]!.GetValue<double>()+sample["end"]![0]!.GetValue<double>())/2),
                (float)((sample["start"]![1]!.GetValue<double>()+sample["end"]![1]!.GetValue<double>())/2),
                (float)(sample["base"]!.GetValue<double>()+sample["height"]!.GetValue<double>()/2));
            var screen=viewport.View.Camera.Project(target,viewport.Bounds.Size)??throw new Exception("Camera projection failed");
            var hit=viewport.View.Camera.Pick(viewport.View.Scene,new Point(screen.X,screen.Y),viewport.Bounds.Size,null,viewport.View.ZMin,viewport.View.ZMax);
            if(hit==null)throw new Exception("3D element picking failed");viewport.ElementSelected?.Invoke(hit);
            if(selectedId!=hit)throw new Exception("3D selection did not reach inspector");
            selectedId=sample["id"]!.GetValue<string>();ShowProperties();
            fields["thickness"].Text="0.27";review.SelectedItem="reviewed";await ApplyAsync();if(!dirty)throw new Exception("Correction did not enter draft state");
            selectedId="ui-window";ShowProperties();fields["width"].Text="0.65";review.SelectedItem="reviewed";await ApplyAsync();
            selectedId="ui-stair";ShowProperties();fields["going"].Text="0.28";review.SelectedItem="reviewed";await ApplyAsync();
            var wallId=sample["id"]!.GetValue<string>();var currentWall=state!["model"]!["walls"]!.AsArray().First(node=>node!["id"]!.GetValue<string>()==wallId)!;
            var dx=currentWall["end"]![0]!.GetValue<double>()-currentWall["start"]![0]!.GetValue<double>();var dy=currentWall["end"]![1]!.GetValue<double>()-currentWall["start"]![1]!.GetValue<double>();
            selectedId=wallId;ShowProperties();splitOffset.Text=(Math.Sqrt(dx*dx+dy*dy)/2).ToString(CultureInfo.InvariantCulture);await SplitWallAsync();
            var splitId=wallId+"-split-2";if(!state!["model"]!["walls"]!.AsArray().Any(node=>node!["id"]!.GetValue<string>()==splitId))throw new Exception("Wall split was not applied");
            await MergeWallsAsync([wallId,splitId]);if(state!["model"]!["walls"]!.AsArray().Any(node=>node!["id"]!.GetValue<string>()==splitId))throw new Exception("Wall merge was not applied");
            await SaveAsync();await LoadAsync(path);if(Math.Abs(state!["model"]!["walls"]![0]!["thickness"]!.GetValue<double>()-.27)>1e-10)throw new Exception("Edit was lost on reopening");
            if(Math.Abs(state!["model"]!["openings"]![0]!["width"]!.GetValue<double>()-.65)>1e-10||Math.Abs(state["model"]!["stairs"]![0]!["going"]!.GetValue<double>()-.28)>1e-10)throw new Exception("Feature edit lost on reopening");
            selectedId=state["model"]!["walls"]![0]!["id"]!.GetValue<string>();ShowProperties();viewport.View.Selected=selectedId;viewport.Redraw();
            await ExportToAsync(Path.Combine(output,"edited.ifc"));
            await Task.Delay(1800);for(var i=0;i<30;i++){viewport.View.Camera.Yaw+=.008f;viewport.Redraw();await Task.Delay(20);}viewport.CaptureGpu(Path.Combine(output,"viewport-gl.png"));await Task.Delay(700);
            using(var bitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height),new Vector(96,96))){bitmap.Render(this);using var outputStream=File.Create(Path.Combine(output,"desktop.png"));bitmap.Save(outputStream,PngBitmapEncoderOptions.Default);}
            File.WriteAllText(Path.Combine(output,"ui-verification.json"),new JsonObject{["edit_survived_reopen"]=true,["wall_topology_edit_survived_reopen"]=true,["ifc_exists"]=File.Exists(Path.Combine(output,"edited.ifc")),["viewport_backend"]=viewport.Backend,["preview_points"]=viewport.View.Scene.Points.Length/7,["conversion_backend"]="CPU",["graphics"]=viewport.Diagnostics()}.ToJsonString());
            dirty=false;Environment.ExitCode=0;Close();
        }
        catch(Exception e){File.WriteAllText(Path.Combine(output,"ui-error.txt"),e.ToString());dirty=false;Environment.ExitCode=1;Close();}
    }
    async Task VerifyPreviewAsync(string[] args)
    {
        var index=Array.IndexOf(args,"--verify-preview");var path=Path.GetFullPath(args[index+1]);var output=Path.GetFullPath(args[index+2]);Directory.CreateDirectory(output);
        try
        {
            var clock=Stopwatch.StartNew();await LoadAsync(path);if(state==null)throw new Exception(status.Text);var loadMs=clock.Elapsed.TotalMilliseconds;
            await Task.Delay(1800);for(var i=0;i<30;i++){viewport.View.Camera.Yaw+=.008f;viewport.Redraw();await Task.Delay(20);}viewport.CaptureGpu(Path.Combine(output,"viewport-gl.png"));await Task.Delay(800);
            using(var bitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height),new Vector(96,96)))
            {bitmap.Render(this);using var stream=File.Create(Path.Combine(output,"desktop.png"));bitmap.Save(stream,PngBitmapEncoderOptions.Default);}
            File.WriteAllText(Path.Combine(output,"preview-verification.json"),new JsonObject{["viewport_backend"]=viewport.Backend,["load_project_ms"]=loadMs,["source_points"]=viewport.View.Scene.TotalPoints,["preview_points"]=viewport.View.Scene.Points.Length/7,["warnings_retained"]=state["warnings"]!.DeepClone(),["conversion_backend"]="CPU",["graphics"]=viewport.Diagnostics()}.ToJsonString());
            Environment.ExitCode=0;Close();
        }
        catch(Exception e){File.WriteAllText(Path.Combine(output,"ui-error.txt"),e.ToString());Environment.ExitCode=1;Close();}
    }
}
