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
using Avalonia.Automation;

namespace Punctora.Desktop;

public sealed class MainWindow : Window
{
    readonly WorkerClient worker=new();
    readonly SceneViewport viewport;
    readonly HeightLegend heightLegend=new();
    readonly TextBlock status=Text("Open a project, import an E57 or try the example.",14);
    readonly TextBlock recognitionStatus=Text("Recognition: choose Classical or check specialist setup before importing a scan.",12);
    readonly Border statusBanner=new(){Background=Brush.Parse("#132238"),Padding=new Thickness(12,9),Margin=new Thickness(0,0,0,12)};
    readonly TextBlock backend=Text("Initializing graphics",11);
    readonly TextBlock frameDiagnostics=Text("Frame diagnostics appear while moving the view.",11);
    readonly ComboBox previewQuality=new(){ItemsSource=new[]{"Adaptive","Low","Medium","High"},SelectedIndex=0,HorizontalAlignment=HorizontalAlignment.Stretch};
    readonly TextBlock projectTitle=Text("No project open",18);
    readonly TextBlock counts=Text("",11);
    readonly TextBlock warnings=Text("Review candidates against the scan before accepting geometry.",12);
    readonly TextBlock evidence=Text("Select a wall, slab, slab opening, stair or storey to review its parameters.",12);
    readonly TextBlock selectedTitle=Text("Element properties",17);
    readonly StackPanel fieldsPanel=new(){Spacing=8};
    readonly Dictionary<string,TextBox> fields=[];
    readonly Dictionary<string,string> initialFields=[];
    readonly ListBox elements=new(){SelectionMode=SelectionMode.Multiple};
    readonly ScrollViewer leftScroll=new(){HorizontalScrollBarVisibility=Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
        VerticalScrollBarVisibility=Avalonia.Controls.Primitives.ScrollBarVisibility.Auto};
    readonly ComboBox storeys=new(){HorizontalAlignment=HorizontalAlignment.Stretch};
    readonly ComboBox method=new(){ItemsSource=new[]{"Contours","Region growing"},SelectedIndex=0};
    readonly ComboBox reconstructionScope=new(){ItemsSource=new[]{"Auto (interior or exterior)","Interior","Exterior / partial scan"},SelectedIndex=0};
    readonly ComboBox reconstructionAction=new(){ItemsSource=new[]{"Replace current model","Add to existing model"},SelectedIndex=0};
    readonly ComboBox recognitionMode=new(){ItemsSource=new[]{"Classical","Punctora specialist","Hybrid specialist + projected evidence"},SelectedIndex=0};
    readonly TextBox specialistModels=new(){Watermark="Folder containing model_A.onnx through model_J.onnx",
        Text=Environment.GetEnvironmentVariable("PUNCTORA_SPECIALIST_MODELS")??""};
    readonly CheckBox sharedSurveyFrame=new(){Content="Scans share survey coordinates (confirm)"};
    readonly TextBox modelAlignment=new(){Watermark="Optional placement: X; Y; Z; yaw degrees"};
    readonly TextBox manualLevels=new(){AcceptsReturn=true,MinHeight=80,TextWrapping=TextWrapping.Wrap,
        Watermark="Level 1; 0; 3\nLevel 2; 3.2; 6.2"};
    readonly ComboBox review=new(){ItemsSource=new[]{"unreviewed","reviewed","flagged","rejected"},SelectedIndex=0,HorizontalAlignment=HorizontalAlignment.Stretch};
    readonly ComboBox classification=new(){ItemsSource=new[]{"unclassified","paired_faces","single_face_candidate","exterior_candidate","consolidated_candidate","interior","exterior"},SelectedIndex=0,HorizontalAlignment=HorizontalAlignment.Stretch};
    readonly CheckBox zUp=new(){Content="Z is up (confirm before fitting)"};
    readonly CheckBox compareBudgets=new(){Content="Compare 250k–5M budgets"};
    readonly Slider section=new(){Minimum=0,Maximum=10,Value=10};
    readonly ComboBox cloudColor=new(){ItemsSource=new[]{"Height","Original","Monochrome"},SelectedIndex=0,HorizontalAlignment=HorizontalAlignment.Stretch};
    readonly Slider pointSize=new(){Minimum=1,Maximum=8,Value=2.5,TickFrequency=.5};
    readonly TextBox cropBottom=new(){PlaceholderText="Unbounded bottom (m)"};
    readonly TextBox cropTop=new(){PlaceholderText="Unbounded top (m)"};
    readonly ProgressBar progress=new(){Minimum=0,Maximum=100,Height=4};
    readonly List<Button> projectActions=[];
    readonly Button save,apply,cancel,undoButton,mergeButton,splitButton,cropDraw,cropApply,cropClear,cropCancel;
    readonly Button addDoorButton,addWindowButton,addStairButton,addLandingButton,addSlabOpeningButton,deleteCandidateButton;
    readonly CheckBox approveSlabCut=new(){Content="Approve this opening as an IFC slab cut"};
    readonly TextBox splitOffset=new(){Watermark="Distance from wall start (m)"};
    readonly Stack<JsonNode> undo=[];
    CancellationTokenSource? jobCancellation;
    JsonObject? state;
    string? projectPath,selectedId;
    bool busy,dirty,refreshing;
    string? progressStageKey;
    int statusPulseVersion;
    string[] elementIds=[];

    public MainWindow(string[] args)
    {
        Title="Punctora BIM Studio | 0.3.0a40 desktop preview";Width=1440;Height=920;MinWidth=800;MinHeight=500;
        Background=Brush.Parse("#0B1220");
        viewport=new SceneViewport(args.Contains("--software")||Environment.GetEnvironmentVariable("PUNCTORA_SOFTWARE_PREVIEW")=="1");
        viewport.BackendChanged=value=>backend.Text=value;
        viewport.FrameDiagnosticsChanged=value=>frameDiagnostics.Text=value;
        viewport.SizeChanged+=(_,_)=>UpdateHeightLegend();
        viewport.ElementSelected=id=>{selectedId=id;var index=Array.IndexOf(elementIds,id);elements.SelectedIndex=index;ShowProperties();viewport.View.Selected=id;viewport.Redraw();};
        var root=new Grid{RowDefinitions=new RowDefinitions("Auto,Auto,Auto,*"),Margin=new Thickness(18,14)};
        var header=new Grid{ColumnDefinitions=new ColumnDefinitions("Auto,*,Auto"),Margin=new Thickness(0,0,0,14)};
        var brand=new StackPanel{Spacing=3};brand.Children.Add(Text("PUNCTORA  /  BIM STUDIO",20));brand.Children.Add(Text("Point clouds to reviewed IFC",11));
        header.Children.Add(brand);Grid.SetColumn(projectTitle,1);projectTitle.Margin=new Thickness(35,0,12,0);header.Children.Add(projectTitle);
        var alpha=Text("M3 PREVIEW 0.3.0a40",11);alpha.Foreground=Brush.Parse("#FBBF24");Grid.SetColumn(alpha,2);header.Children.Add(alpha);root.Children.Add(header);
        var toolbar=new WrapPanel{Orientation=Orientation.Horizontal,ItemSpacing=8,LineSpacing=8,Margin=new Thickness(0,0,0,14)};
        Button Action(string label,Func<Task> action){var button=Button(label,async()=>await Guard(action));toolbar.Children.Add(button);projectActions.Add(button);return button;}
        Action("Import E57",ImportAsync);Action("Example",DemoAsync);Action("Open",OpenAsync);
        save=Action("Save",SaveAsync);Action("Save copy",CopyAsync);Action("Detect elements",ReconstructAsync);Action("Convert to IFC",ExportAsync);
        Action("Add saved project model",AddProjectModelAsync);
        undoButton=Action("Undo edit",UndoAsync);Action("Revert",RevertAsync);
        cancel=Button("Cancel job",()=>{jobCancellation?.Cancel();return Task.CompletedTask;});cancel.IsEnabled=false;toolbar.Children.Add(cancel);
        Grid.SetRow(toolbar,1);root.Children.Add(toolbar);
        var body=new Grid{ColumnDefinitions=new ColumnDefinitions("240,12,*,12,295")};Grid.SetRow(body,3);root.Children.Add(body);
        var left=new StackPanel{Margin=new Thickness(12)};
        var options=new StackPanel{Spacing=9};options.Children.Add(Text("VIEW & ELEMENT DETECTION",12));options.Children.Add(storeys);
        var cloud=new CheckBox{Content="Point cloud",IsChecked=true};var model=new CheckBox{Content="Model candidates",IsChecked=true};
        cloud.IsCheckedChanged+=(_,_)=>{viewport.View.Cloud=cloud.IsChecked==true;UpdateHeightLegend();viewport.Redraw();};
        model.IsCheckedChanged+=(_,_)=>{viewport.View.Model=model.IsChecked==true;viewport.Redraw();};options.Children.Add(cloud);options.Children.Add(model);
        options.Children.Add(Text("Point cloud colours",11));options.Children.Add(cloudColor);
        options.Children.Add(Text("Preview quality",11));options.Children.Add(previewQuality);
        previewQuality.SelectionChanged+=(_,_)=>viewport.SetQuality((PreviewQuality)Math.Max(0,previewQuality.SelectedIndex));
        cloudColor.SelectionChanged+=(_,_)=>{viewport.View.CloudColor=cloudColor.SelectedIndex switch{1=>CloudColorMode.Original,2=>CloudColorMode.Monochrome,_=>CloudColorMode.Height};UpdateHeightLegend();viewport.Redraw();};
        var pointSizeLabel=Text("Point size: 2.5 px",11);options.Children.Add(pointSizeLabel);options.Children.Add(pointSize);
        pointSize.PropertyChanged+=(_,e)=>{if(e.Property==Slider.ValueProperty){viewport.View.PointSize=(float)pointSize.Value;pointSizeLabel.Text=$"Point size: {pointSize.Value:F1} px";viewport.Redraw();}};
        options.Children.Add(Text("PROJECT CROP",12));options.Children.Add(cropBottom);options.Children.Add(cropTop);
        cropDraw=Button("Draw polygon",()=>{if(state==null)return Task.CompletedTask;viewport.BeginCropDrawing();UpdateActions();status.Text="Crop drawing: left-click vertices, right-click removes the last vertex, then choose Apply crop.";return Task.CompletedTask;});
        cropApply=Button("Apply crop",()=>Guard(ApplyCropAsync));cropClear=Button("Clear crop",()=>Guard(ClearCropAsync));
        cropCancel=Button("Cancel polygon",()=>{viewport.CancelCropDrawing();UpdateActions();status.Text="Crop drawing cancelled.";return Task.CompletedTask;});
        foreach(var button in new[]{cropDraw,cropApply,cropClear,cropCancel}){options.Children.Add(button);projectActions.Add(button);}
        options.Children.Add(Text("Crop is non-destructive. Save it, then run Detect elements to restrict reconstruction.",11));
        options.Children.Add(Button("Fit view",()=>{viewport.FitVisible();return Task.CompletedTask;}));
        options.Children.Add(Text("Model opacity",11));var opacity=new Slider{Minimum=.05,Maximum=1,Value=1};opacity.PropertyChanged+=(_,e)=>{if(e.Property==Slider.ValueProperty){viewport.View.Opacity=(float)opacity.Value;viewport.Redraw();}};options.Children.Add(opacity);
        options.Children.Add(Text("Section: visible below height",11));options.Children.Add(section);
        section.PropertyChanged+=(_,e)=>{if(e.Property==Slider.ValueProperty)FilterStorey();};
        options.Children.Add(Text("Surface method",11));options.Children.Add(method);options.Children.Add(zUp);options.Children.Add(compareBudgets);
        options.Children.Add(Text("Reconstruction scope",11));options.Children.Add(reconstructionScope);
        options.Children.Add(Text("Result action",11));options.Children.Add(reconstructionAction);
        options.Children.Add(Text("Recognition mode",11));options.Children.Add(recognitionMode);
        options.Children.Add(specialistModels);
        var chooseSpecialists=Button("Choose specialist model folder",ChooseSpecialistFolderAsync);options.Children.Add(chooseSpecialists);projectActions.Add(chooseSpecialists);
        var checkSpecialists=Button("Check specialist setup",CheckSpecialistSetupAsync);options.Children.Add(checkSpecialists);projectActions.Add(checkSpecialists);
        options.Children.Add(Text("The portable app includes CPU specialist inference. Select your existing A-J model folder and check setup. Unavailable specialist runs stop before opening the scan; choose Classical explicitly to run without AI.",11));
        options.Children.Add(Text("Manual level bounds (optional)",11));options.Children.Add(manualLevels);
        options.Children.Add(Text("One row: name; bottom; top, in local metres. Save settings, then detect. Empty uses automatic bounds.",11));
        void SetupChanged(){if(refreshing||state==null||busy)return;dirty=true;UpdateActions();}
        reconstructionScope.SelectionChanged+=(_,_)=>SetupChanged();
        manualLevels.PropertyChanged+=(_,e)=>{if(e.Property==TextBox.TextProperty)SetupChanged();};
        var software=new CheckBox{Content="Use software preview",IsChecked=viewport.SoftwareMode};
        software.IsCheckedChanged+=(_,_)=>{if(software.IsChecked==true)viewport.UseSoftware("Selected in settings");else viewport.UseAutomatic();};options.Children.Add(software);
        options.Children.Add(sharedSurveyFrame);options.Children.Add(modelAlignment);
        options.Children.Add(Text("Add saved project uses shared survey coordinates or the explicit placement above. Existing edits and evidence are retained.",11));
        options.Children.Add(Text("ELEMENTS",12));left.Children.Add(options);elements.Height=220;elements.Margin=new Thickness(0,8,0,0);left.Children.Add(elements);
        leftScroll.SizeChanged+=(_,_)=>elements.Height=Math.Min(220,Math.Max(60,leftScroll.Bounds.Height-32));
        leftScroll.Content=left;body.Children.Add(Panel(leftScroll));
        var center=new Grid{RowDefinitions=new RowDefinitions("*,Auto")};Grid.SetColumn(center,2);body.Children.Add(center);
        center.Children.Add(new Border{Child=viewport,CornerRadius=new CornerRadius(10),ClipToBounds=true});
        center.Children.Add(heightLegend);
        var viewFooter=new StackPanel{Spacing=4,Margin=new Thickness(8,8,8,0)};viewFooter.Children.Add(counts);viewFooter.Children.Add(Text("Drag: orbit  ·  Right-drag: pan  ·  Wheel: zoom  ·  Click model: select",11));viewFooter.Children.Add(frameDiagnostics);viewFooter.Children.Add(backend);
        var viewDetails=new ScrollViewer{Content=viewFooter,MaxHeight=84,HorizontalScrollBarVisibility=Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled};
        Grid.SetRow(viewDetails,1);center.Children.Add(viewDetails);
        var inspector=new StackPanel{Spacing=10,Margin=new Thickness(14)};inspector.Children.Add(selectedTitle);inspector.Children.Add(fieldsPanel);inspector.Children.Add(Text("Review state",11));inspector.Children.Add(review);inspector.Children.Add(Text("Wall classification",11));inspector.Children.Add(classification);
        inspector.Children.Add(approveSlabCut);
        apply=Button("Apply correction",ApplyAsync);inspector.Children.Add(apply);
        inspector.Children.Add(Text("FEATURE CORRECTIONS",11));
        addDoorButton=Button("Add door to selected wall",()=>AddCandidateAsync("door"));inspector.Children.Add(addDoorButton);
        addWindowButton=Button("Add window to selected wall",()=>AddCandidateAsync("window"));inspector.Children.Add(addWindowButton);
        addStairButton=Button("Add stair to selected storey",()=>AddCandidateAsync("stair"));inspector.Children.Add(addStairButton);
        addLandingButton=Button("Add landing to selected stair",()=>AddCandidateAsync("landing"));inspector.Children.Add(addLandingButton);
        addSlabOpeningButton=Button("Add opening to selected slab",()=>AddCandidateAsync("slab_opening"));inspector.Children.Add(addSlabOpeningButton);
        deleteCandidateButton=Button("Delete selected candidate",DeleteCandidateAsync);inspector.Children.Add(deleteCandidateButton);
        inspector.Children.Add(Text("WALL TOPOLOGY",11));
        mergeButton=Button("Merge selected wall fragments",()=>MergeWallsAsync());inspector.Children.Add(mergeButton);
        inspector.Children.Add(splitOffset);splitButton=Button("Split selected wall",SplitWallAsync);inspector.Children.Add(splitButton);
        inspector.Children.Add(Text("Ctrl-click wall rows to select fragments for merging. Split distance is measured from the selected wall start.",11));
        inspector.Children.Add(Text("SCAN EVIDENCE & ASSUMPTIONS",11));inspector.Children.Add(evidence);inspector.Children.Add(Text("PROJECT FINDINGS",11));inspector.Children.Add(warnings);
        var right=Panel(new ScrollViewer{Content=inspector,HorizontalScrollBarVisibility=Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled});Grid.SetColumn(right,4);body.Children.Add(right);
        // Persistent top feedback. Colors supplement readable state text.
        // A brief non-layout color highlight marks real stage changes; it does
        // not repeat for elapsed-time heartbeats or replace the readable text.
        var feedback=new StackPanel{Spacing=5};
        feedback.Children.Add(new ScrollViewer{Content=status,MaxHeight=76,HorizontalScrollBarVisibility=Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled});
        feedback.Children.Add(new ScrollViewer{Content=recognitionStatus,MaxHeight=44,HorizontalScrollBarVisibility=Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled});
        feedback.Children.Add(progress);
        status.FontWeight=FontWeight.SemiBold;
        statusBanner.Child=feedback;Grid.SetRow(statusBanner,2);root.Children.Add(statusBanner);
        AutomationProperties.SetName(statusBanner,"Operation status and recognition provider");
        status.PropertyChanged+=(_,e)=>{if(e.Property==TextBlock.TextProperty)UpdateStatusColor();};
        recognitionStatus.PropertyChanged+=(_,e)=>{if(e.Property==TextBlock.TextProperty)UpdateStatusColor();};
        Content=root;
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
        cancel.IsEnabled=busy;apply.IsEnabled=!busy&&selectedId!=null;save.IsEnabled=!busy&&dirty;undoButton.IsEnabled=!busy&&undo.Count>0;
        var selectedWalls=SelectedWallIds();var selected=Selected();mergeButton.IsEnabled=!busy&&selectedWalls.Length>=2;splitButton.IsEnabled=!busy&&selected!=null&&selected.Value.Kind=="walls";splitOffset.IsEnabled=splitButton.IsEnabled;
        addDoorButton.IsEnabled=addWindowButton.IsEnabled=!busy&&selected?.Kind=="walls";
        addStairButton.IsEnabled=!busy&&selected?.Kind=="storeys";
        addLandingButton.IsEnabled=!busy&&selected?.Kind=="stairs";
        addSlabOpeningButton.IsEnabled=!busy&&selected?.Kind=="slabs";
        approveSlabCut.IsEnabled=!busy&&selected?.Kind=="slab_openings";
        approveSlabCut.IsVisible=selected?.Kind=="slab_openings";
        deleteCandidateButton.IsEnabled=!busy&&selected!=null&&new[]{"openings","stairs","landings","slab_openings"}.Contains(selected.Value.Kind);
        method.IsEnabled=zUp.IsEnabled=!busy;
        reconstructionScope.IsEnabled=manualLevels.IsEnabled=!busy&&state!=null;
        recognitionMode.IsEnabled=specialistModels.IsEnabled=!busy;
        cropBottom.IsEnabled=cropTop.IsEnabled=!busy&&state!=null;
        cropDraw.IsEnabled=cropApply.IsEnabled=cropClear.IsEnabled=!busy&&state!=null;
        cropCancel.IsEnabled=!busy&&viewport.CropDrawing;
        foreach(var field in fields.Values)field.IsEnabled=!busy;
        review.IsEnabled=classification.IsEnabled=!busy&&selectedId!=null;
        projectTitle.Text=state==null?"No project open":state["name"]!.GetValue<string>()+(dirty?"  * unsaved corrections":"");
    }
    bool RequireClean(){if(!dirty)return true;status.Text="Save or revert your corrections before opening or reconstructing another project.";return false;}
    void UpdateStatusColor()
    {
        var text=status.Text??"";
        var provider=recognitionStatus.Text??"";
        var failed=new[]{"failed","blocked","unavailable","FALLBACK"}.Any(word=>text.Contains(word,StringComparison.OrdinalIgnoreCase))
            ||provider.Contains("FALLBACK:")||provider.Contains("Actual: unavailable");
        var complete=new[]{"saved","Completed","ready","exported","passed"}.Any(word=>text.Contains(word,StringComparison.OrdinalIgnoreCase));
        statusBanner.Background=Brush.Parse(failed?"#3A202B":complete?"#12352E":"#132238");
        status.Foreground=Brush.Parse(failed?"#FBBF24":complete?"#A7F3D0":"#F1F5F9");
    }
    void ApplyProgress(int value,string phase)
    {
        progress.IsIndeterminate=false;progress.Value=value;status.Text=phase;
        if(phase.StartsWith("Stage 1/9: preflight passed",StringComparison.Ordinal))
            recognitionStatus.Text="Provider: PunctoraSpecialistProvider · Runtime: CPUExecutionProvider · A-J ready";
        var key=phase.Split(" · ",2,StringSplitOptions.None)[0];
        if(phase.StartsWith("Stage ",StringComparison.Ordinal)&&key!=progressStageKey)
        {
            progressStageKey=key;
            var version=++statusPulseVersion;
            statusBanner.Background=Brush.Parse("#1B4167");
            _=ResetStatusHighlightAsync(version);
        }
    }
    async Task ResetStatusHighlightAsync(int version)
    {
        await Task.Delay(450);
        if(version==statusPulseVersion)Dispatcher.UIThread.Post(UpdateStatusColor);
    }
    void ShowRecognitionStatus(JsonNode? recognition)
    {
        if(recognition==null){recognitionStatus.Text="Recognition: Classical. Specialist inference has not run.";return;}
        var active=recognition["active_branches"]?.AsArray().Select(n=>n!.GetValue<string>())??[];
        var missing=recognition["missing_branches"]?.AsArray().Select(n=>n!.GetValue<string>())??[];
        recognitionStatus.Text=$"Requested: {recognition["requested_provider"]?.GetValue<string>()??"classical"} · Actual: {recognition["actual_provider"]?.GetValue<string>()??"unavailable"} · Active A-J: {string.Join(", ",active)} · Missing: {string.Join(", ",missing)}";
        if(recognition["branch_status"]?.GetValue<string>()=="assets_verified_inference_pending")
            recognitionStatus.Text="PunctoraSpecialistProvider setup verified · CPU runtime and A-J assets ready · Model inference has not started.";
        if(recognition["fallback_reason"]?.GetValue<string>() is { } reason)
            recognitionStatus.Text+=" · FALLBACK: "+reason;
    }
    async Task<JsonObject?> RunAsync(string command,string path,JsonObject? extra=null)
    {
        if(busy)return null;
        busy=true;jobCancellation=new();progressStageKey=null;UpdateActions();progress.Value=0;progress.IsIndeterminate=true;
        status.Text="Running: "+command;
        var request=extra??new JsonObject();request["command"]=command;request["project"]=path;
        try
        {
            var result=await worker.RunAsync(request,(value,phase)=>Dispatcher.UIThread.Post(()=>ApplyProgress(value,phase)),jobCancellation.Token);
            var geometryBackend=result?["processing_backend"]?.GetValue<string>()
                ?? result?["model"]?["metadata"]?["performance"]?["compute_backend"]?.GetValue<string>();
            status.Text=geometryBackend==null?"Completed":"Completed · geometry: "+geometryBackend;
            progress.Value=100;return result;
        }
        catch(OperationCanceledException)
        {
            status.Text="Job stopped. Saved work is preserved.";
            var cancelledJobId=request["job_id"]?.GetValue<string>();
            if(cancelledJobId!=null&&command!="preflight_recognition")
                await worker.RunAsync(new JsonObject{["command"]="record_cancelled",["project"]=path,
                    ["cancelled_job_id"]=cancelledJobId},null,CancellationToken.None);
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
        catch(Exception e)
        {
            if(command=="reconstruct"&&request["recognition_mode"]?.GetValue<string>() is "specialist" or "hybrid")
                recognitionStatus.Text=e.Message.Contains("blocked before reconstruction")
                    ?"Latest attempt requested PunctoraSpecialistProvider · Actual: unavailable · Scan processing did not start; saved model preserved."
                    :"Latest attempt requested PunctoraSpecialistProvider · Recognition incomplete; see last-performance.json. Saved model preserved.";
            status.Text="Job failed: "+e.Message;return null;
        }
        finally{busy=false;++statusPulseVersion;progress.IsIndeterminate=false;jobCancellation.Dispose();jobCancellation=null;UpdateActions();}
    }
    JsonObject DetectionOptions()
    {
        var levels=new JsonArray();
        foreach(var row in (manualLevels.Text??"").Split('\n',StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries))
        {
            var parts=row.Split(';',StringSplitOptions.TrimEntries);
            if(parts.Length!=3||string.IsNullOrWhiteSpace(parts[0]))throw new InvalidDataException("Manual levels: use name; bottom; top, one row per level.");
            var bottom=Parse(parts[1]);var top=Parse(parts[2]);
            if(top<=bottom)throw new InvalidDataException("Manual level top must be above its bottom.");
            levels.Add(new JsonObject{["name"]=parts[0],["bottom_m"]=bottom,["top_m"]=top});
        }
        return new JsonObject{["scope"]=reconstructionScope.SelectedIndex switch{1=>"interior",2=>"exterior",_=>"auto"},["manual_levels"]=levels};
    }
    JsonObject ModelRequest()=>new(){["expected_revision"]=state!["revision"]!.DeepClone(),["model"]=state["model"]?.DeepClone(),
        ["reconstruction_options"]=DetectionOptions(),
        ["crop"]=state["crop"]!.DeepClone(),["model_crop"]=state["model_crop"]!.DeepClone(),["model_crop_stale"]=state["model_crop_stale"]!.DeepClone()};
    JsonObject DraftSnapshot()=>new(){["model"]=state!["model"]?.DeepClone(),["crop"]=state["crop"]!.DeepClone(),
        ["model_crop"]=state["model_crop"]!.DeepClone(),["model_crop_stale"]=state["model_crop_stale"]!.DeepClone()};
    void UpdateHeightLegend()
    {
        heightLegend.SetScale(viewport.View.Scene.HeightMinimum,viewport.View.Scene.HeightMaximum);
        heightLegend.IsVisible=state is not null&&viewport.View.Cloud&&viewport.View.CloudColor==CloudColorMode.Height
            &&viewport.Bounds.Width>=300&&viewport.Bounds.Height>=220;
        heightLegend.Tag=viewport.View.Scene.HeightScaleScope;
    }
    async Task PresentAsync(string path,JsonObject value,bool fit)
    {
        viewport.CancelCropDrawing();
        SceneData scene;
        string? previewFailure=null;
        try{scene=await Task.Run(()=>SceneData.Load(path,value));}
        catch(InvalidDataException e) when(value["model"] is JsonObject)
        {
            // The worker has already atomically saved this revision. A model
            // display failure must not leave requests using the old revision.
            var cloudOnly=value.DeepClone().AsObject();cloudOnly["model"]=null;
            scene=await Task.Run(()=>SceneData.Load(path,cloudOnly));
            previewFailure="Model preview failed: "+e.Message+". Saved reconstruction retained; point cloud shown. You can reopen, retry detection or export.";
        }
        state=value;projectPath=path;viewport.SetScene(scene,fit);UpdateHeightLegend();refreshing=true;
        try
        {
            var setup=state["reconstruction_options"] as JsonObject;
            reconstructionScope.SelectedIndex=setup?["scope"]?.GetValue<string>() switch{"interior"=>1,"exterior"=>2,_=>0};
            recognitionMode.SelectedIndex=state["recognition"]?["requested_mode"]?.GetValue<string>() switch{"specialist"=>1,"hybrid"=>2,_=>0};
            ShowRecognitionStatus(state["recognition"]);
            manualLevels.Text=string.Join("\n",(setup?["manual_levels"]?.AsArray()??[]).Select(row=>
                row!["name"]!.GetValue<string>()+"; "+row["bottom_m"]!.GetValue<double>().ToString("G17",CultureInfo.InvariantCulture)+"; "+
                row["top_m"]!.GetValue<double>().ToString("G17",CultureInfo.InvariantCulture)));
            var crop=state["crop"]!.AsObject();
            var cropPolygon=crop["polygon"] is JsonArray polygon?polygon.Select(p=>new System.Numerics.Vector2(
                (float)p![0]!.GetValue<double>(),(float)p[1]!.GetValue<double>())).ToList():null;
            float? cropLow=crop["z_min"] is { } low?(float)low.GetValue<double>():null;
            float? cropHigh=crop["z_max"] is { } high?(float)high.GetValue<double>():null;
            viewport.SetCrop(cropPolygon,cropLow,cropHigh);
            cropBottom.Text=cropLow?.ToString("G10",CultureInfo.InvariantCulture)??"";
            cropTop.Text=cropHigh?.ToString("G10",CultureInfo.InvariantCulture)??"";
            var priorStorey=viewport.View.Storey;
            var model=state["model"] as JsonObject;
            var levels=model?["storeys"]?.AsArray()??[];
            storeys.ItemsSource=new[]{"All storeys"}.Concat(levels.Select(s=>s!["name"]!.GetValue<string>())).ToArray();
            storeys.SelectedIndex=priorStorey==null?0:Math.Max(0,levels.ToList().FindIndex(s=>s!["id"]!.GetValue<string>()==priorStorey)+1);
            var nodes=model==null?new List<(string Kind,JsonObject Node)>():new[]{"storeys","walls","slabs","slab_openings","openings","stairs","landings","facade_panels"}.SelectMany(kind=>(model[kind]?.AsArray()??[]).Select(n=>(Kind:kind,Node:n!.AsObject()))).ToList();
            elementIds=nodes.Select(n=>n.Node["id"]!.GetValue<string>()).ToArray();
            elements.ItemsSource=nodes.Select(n=>$"{(n.Kind=="slab_openings"?(n.Node["preview_geometry"]?["ifc_cut_eligible"]?.GetValue<bool>()==true?"slab cut":"slab gap review"):n.Kind)} · {n.Node["id"]}\n{n.Node["review_state"]?.GetValue<string>()??"levels / inferred outline"}").ToArray();
            elements.SelectedIndex=Array.IndexOf(elementIds,selectedId);
            zUp.IsChecked=state["coordinate_confirmation"]!["z_up"]!.GetValue<bool>();
            section.Minimum=scene.Minimum.Z-.5;section.Maximum=scene.Maximum.Z+.5;
            if(fit)section.Value=section.Maximum;else section.Value=Math.Clamp(section.Value,section.Minimum,section.Maximum);
            warnings.Text=string.Join("\n\n",state["warnings"]!.AsArray().Select(n=>n!.GetValue<string>()).Concat(model?["warnings"]?.AsArray().Select(n=>n!.GetValue<string>())??[]).Distinct());
            var performance=model?["metadata"]?["performance"] as JsonObject;
            var computeBackend=performance?["compute_backend"]?.GetValue<string>();
            backend.Text=viewport.Backend;
            var cropState=cropPolygon!=null||cropLow!=null||cropHigh!=null
                ?(state["model_crop_stale"]!.GetValue<bool>()?" · crop changed, detection required":" · crop active"):"";
            var slabCuts=model?["slab_openings"]?.AsArray().Count(o=>o!["preview_geometry"]?["ifc_cut_eligible"]?.GetValue<bool>()==true)??0;
            var slabReviews=model?["slab_openings"]?.AsArray().Count(o=>o!["preview_geometry"]?["ifc_cut_eligible"]?.GetValue<bool>()!=true&&o["review_state"]?.GetValue<string>()!="rejected")??0;
            var openingReviews=model?["metadata"]?["opening_boundary_validation"]?.AsArray().Count(r=>r?["action"]?.GetValue<string>()=="review_only")??0;
            var recognition=state["recognition"] as JsonObject;
            var active=recognition?["active_branches"] is JsonArray activeBranches?string.Join("",activeBranches.Select(n=>n!.GetValue<string>())):"";
            var missing=recognition?["missing_branches"] is JsonArray missingBranches?string.Join("",missingBranches.Select(n=>n!.GetValue<string>())):"";
            var recognitionState=recognition==null?"":$" · recognition: {recognition["requested_provider"]?.GetValue<string>()} requested, {recognition["actual_provider"]?.GetValue<string>()} actual · active [{active}] · missing/failed [{missing}]";
            counts.Text=$"Preview: {scene.Points.Length/7:N0} of {scene.TotalPoints:N0} points · {model?["walls"]?.AsArray().Count??0} walls, {model?["slabs"]?.AsArray().Count??0} slabs, {slabCuts} slab cuts, {slabReviews} gap reviews, {model?["openings"]?.AsArray().Count??0} wall openings, {openingReviews} opening reviews, {model?["stairs"]?.AsArray().Count??0} flights, {model?["landings"]?.AsArray().Count??0} landings · local metres{cropState}{recognitionState}";
        }
        finally{refreshing=false;}
        ShowProperties();FilterStorey();UpdateActions();
        if(previewFailure!=null){status.Text=previewFailure;counts.Text+=" · model preview unavailable";}
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
        foreach(var kind in new[]{"storeys","walls","slabs","slab_openings","openings","stairs","landings","facade_panels"})
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
        FilterStorey();
        fields.Clear();initialFields.Clear();fieldsPanel.Children.Clear();var selection=Selected();
        if(selection==null){selectedTitle.Text="Element properties";evidence.Text="Select a wall, slab, slab opening, wall opening, stair, landing or storey.";UpdateActions();return;}
        var (kind,obj)=selection.Value;selectedTitle.Text=obj["id"]!.GetValue<string>();
        void Field(string key,string label,string value)
        {
            fieldsPanel.Children.Add(Text(label,11));var box=new TextBox{Text=value,Name="Edit_"+key};fields[key]=box;initialFields[key]=value;fieldsPanel.Children.Add(box);
        }
        void Number(string key,string label)=>Field(key,label,obj[key]!.GetValue<double>().ToString("G10",CultureInfo.InvariantCulture));
        if(kind=="walls"||kind=="facade_panels")
        {
            for(var j=0;j<2;j++)foreach(var key in new[]{"start","end"})Field(key+j,key+" "+(j==0?"X":"Y")+" (m)",obj[key]![j]!.GetValue<double>().ToString("G10",CultureInfo.InvariantCulture));
            Number("base","Base (m)");Number("height","Height (m)");Number("thickness","Thickness (m)");
            var dx=obj["end"]![0]!.GetValue<double>()-obj["start"]![0]!.GetValue<double>();var dy=obj["end"]![1]!.GetValue<double>()-obj["start"]![1]!.GetValue<double>();
            splitOffset.Text=(Math.Sqrt(dx*dx+dy*dy)/2).ToString("G10",CultureInfo.InvariantCulture);
            if(obj["evidence"]?["slices"] is JsonArray slices && slices.Count>0)
            {
                fieldsPanel.Children.Add(Text("Inspect wall evidence by height band",11));
                var bands=slices.Where(s=>s!=null).GroupBy(s=>s!["slice_index"]!.GetValue<int>()).OrderBy(g=>g.Key).ToArray();
                var selector=new ComboBox{HorizontalAlignment=HorizontalAlignment.Stretch,
                    ItemsSource=new[]{"All height bands"}.Concat(bands.Select(g=>$"Band {g.Key+1}: {g.First()!["z_min"]!.GetValue<double>():F2} to {g.First()!["z_max"]!.GetValue<double>():F2} m")).ToArray(),SelectedIndex=0};
                var details=Text("Choose a band to isolate cloud points and inspect its measured extent.",11);
                selector.SelectionChanged+=(_,_)=>
                {
                    if(selector.SelectedIndex<=0){FilterStorey();details.Text="All height bands.";return;}
                    var records=bands[selector.SelectedIndex-1].ToArray();var band=records[0]!;
                    viewport.View.ZMin=(float)band["z_min"]!.GetValue<double>();viewport.View.ZMax=(float)band["z_max"]!.GetValue<double>();viewport.Redraw();
                    details.Text=string.Join("\n",records.Select(s=>$"Face {s!["start"]!.ToJsonString()} to {s["end"]!.ToJsonString()}\nCoverage: {s["coverage"]?.ToJsonString()??"unknown"}; original fit points: {s["original_inlier_fit_points"]?.ToJsonString()??"unknown"}; proposal points: {s["proposal_support_points"]}; original RMSE: {s["original_plane_fit_rmse_m"]?.ToJsonString()??"unknown"} m"));
                };
                fieldsPanel.Children.Add(selector);fieldsPanel.Children.Add(details);
            }
        }
        else if(kind=="slabs"){Number("base","Base (m)");Number("thickness","Thickness (m)");}
        else if(kind=="openings")
        {
            Field("host_wall_id","Host wall ID",obj["host_wall_id"]!.GetValue<string>());
            Field("kind","Kind (door / window / unknown)",obj["kind"]!.GetValue<string>());
            foreach(var key in new[]{"offset","sill","width","height"})Number(key,key+" (m)");
        }
        else if(kind=="slab_openings")
        {
            Field("host_slab_id","Host slab ID",obj["host_slab_id"]!.GetValue<string>());
            for(var j=0;j<2;j++)foreach(var key in new[]{"start","end"})Field(key+j,key+" "+(j==0?"X":"Y")+" (m)",obj[key]![j]!.GetValue<double>().ToString("G10",CultureInfo.InvariantCulture));
            Number("width","Width (m)");
        }
        else if(kind=="stairs")
        {
            for(var j=0;j<2;j++)foreach(var key in new[]{"start","end"})Field(key+j,key+" "+(j==0?"X":"Y")+" (m)",obj[key]![j]!.GetValue<double>().ToString("G10",CultureInfo.InvariantCulture));
            foreach(var key in new[]{"base","width","rise","going","tread_thickness"})Number(key,key+" (m)");
            Field("steps","Number of treads",obj["steps"]!.GetValue<int>().ToString(CultureInfo.InvariantCulture));
        }
        else if(kind=="landings")
        {
            Number("base","Base (m)");Number("thickness","Thickness (m)");
            Field("system_id","Stair system ID",obj["system_id"]?.GetValue<string>()??"");fields["system_id"].IsReadOnly=true;
        }
        else{Field("name","Storey name",obj["name"]!.GetValue<string>());Number("elevation","Floor level (m)");Number("ceiling","Ceiling level (m)");}
        review.SelectedItem=obj["review_state"]?.GetValue<string>()??"unreviewed";review.IsVisible=kind!="storeys";
        approveSlabCut.IsChecked=obj["ifc_cut_approved"]?.GetValue<bool>()==true;
        classification.SelectedItem=obj["classification"]?.GetValue<string>()??"unclassified";classification.IsVisible=kind=="walls";
        var provenance=obj["provenance"]?.AsObject().Select(p=>$"{p.Key}: {p.Value}")??[];
        evidence.Text=(kind=="walls"?$"Supporting original points: {obj["evidence_count"]}\nObserved-face fit RMSE: {obj["fit_rmse_m"]?.ToJsonString()??"unknown"} m\n\n":"")+string.Join("\n",provenance)+"\n\nObserved faces and fit statistics refer to the original fit. Corrections are recorded as user supplied.";
        if(kind=="openings"||kind=="stairs"||kind=="landings"||kind=="slab_openings"||kind=="slabs")evidence.Text=$"Geometric support score: {obj["confidence"]?.ToJsonString()??"unknown"} (not an accuracy probability)\n{obj["evidence"]?["scope"]?.GetValue<string>()??"Caller-supplied geometry"}\n\n"+evidence.Text;
        if(kind=="slabs")evidence.Text=$"Supported area: {obj["evidence"]?["supported_percent"]?.ToJsonString()??"unknown"}%\nInferred area: {obj["evidence"]?["inferred_percent"]?.ToJsonString()??"unknown"}%\n\n"+evidence.Text;
        if(kind=="stairs")evidence.Text=$"System: {obj["system_id"]} ({obj["evidence"]?["system_layout"]})\nObserved tread indices: {obj["evidence"]?["observed_step_indices"]}\nInferred missing treads: {obj["evidence"]?["inferred_missing_step_indices"]}\nRiser support: {obj["evidence"]?["riser_support_counts"]}\nLower/upper slabs: {obj["evidence"]?["lower_slab_id"]} / {obj["evidence"]?["upper_slab_id"]}\n\n"+evidence.Text;
        if(kind=="landings")evidence.Text=$"Connected flights: {obj["connected_stair_ids"]}\nObserved support points: {obj["evidence"]?["support_points"]}\n\n"+evidence.Text;
        if(kind=="slab_openings")evidence.Text=$"IFC slab cut: {(obj["preview_geometry"]?["ifc_cut_eligible"]?.GetValue<bool>()==true?"validated / approved":"review only; slab remains filled")}\nValidation basis: {obj["evidence"]?["validation_basis"]}\nMarking reviewed alone does not approve a cut. Use the approval checkbox and Apply correction.\n\nStair validation: {obj["evidence"]?["stair_validation"]??obj["evidence"]?["validation_state"]}\nObserved overlap: {obj["evidence"]?["observed_overlap_m2"]} m2\nAdditional cut: {obj["evidence"]?["additional_cut_area_m2"]} m2\nBoundary justification: {obj["evidence"]?["boundary_justification"]}\n\n"+evidence.Text;
        if(kind=="walls"&&obj["evidence"]?["endpoints"] is JsonArray ends)evidence.Text="Endpoint evidence:\n"+string.Join("\n",ends.Select(e=>$"{e!["end"]}: {e["status"]}"))+"\n\n"+evidence.Text;
        if(kind=="openings")evidence.Text=$"Jamb positions: {obj["evidence"]?["jamb_positions_m"]?.ToJsonString()??"unknown"} m\nSill/head elevations: {obj["evidence"]?["sill_elevation_m"]} / {obj["evidence"]?["head_elevation_m"]} m\nSigned filling depth: {obj["evidence"]?["signed_interior_depth_m"]?.ToJsonString()??"unobserved"} m\nFrame support: {obj["evidence"]?["edge_support"]?.ToJsonString()??"unknown"}\n\n"+evidence.Text;
        if(kind=="openings"&&obj["evidence"]?["facade_system"] is JsonObject facade)
            evidence.Text=$"Glazing: {obj["evidence"]?["classification"]}\nFaçade proposal: {facade["representation"]} ({facade["panel_count"]} bays)\nEditing or flagging a bay disables the whole façade assembly; individual windows remain.\n\n"+evidence.Text;
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
            JsonNode value=key=="name"||key=="kind"||key=="host_wall_id"||key=="host_slab_id"||key=="system_id"?JsonValue.Create(box.Text?.Trim()??"")!:key=="steps"?JsonValue.Create(int.Parse(box.Text??"",CultureInfo.InvariantCulture))!:JsonValue.Create(Parse(box.Text??""))!;
            if(value.ToJsonString()!=obj[key]!.ToJsonString())changes[key]=value;
        }
        if(kind=="walls"||kind=="facade_panels"||kind=="stairs"||kind=="slab_openings")foreach(var key in new[]{"start","end"})
        {
            if(fields[key+0].Text==initialFields[key+0]&&fields[key+1].Text==initialFields[key+1])continue;
            var array=new JsonArray(Enumerable.Range(0,2).Select(j=>fields[key+j].Text==initialFields[key+j]?obj[key]![j]!.DeepClone():JsonValue.Create(Parse(fields[key+j].Text??""))).ToArray());
            if(array.ToJsonString()!=obj[key]!.ToJsonString())changes[key]=array;
        }
        if(kind!="storeys"&&review.SelectedItem is string r&&r!=obj["review_state"]!.GetValue<string>())changes["review_state"]=r;
        if(kind=="walls"&&classification.SelectedItem is string c&&c!=obj["classification"]!.GetValue<string>())changes["classification"]=c;
        if(kind=="slab_openings"&&(approveSlabCut.IsChecked==true)!=(obj["ifc_cut_approved"]?.GetValue<bool>()==true))changes["ifc_cut_approved"]=approveSlabCut.IsChecked==true;
        if(changes.Count==0){status.Text="No parameters changed.";return;}
        var previous=DraftSnapshot();var request=ModelRequest();request["element_id"]=selectedId;request["changes"]=changes;
        var result=await RunAsync("edit",projectPath,request);
        if(result==null)return;
        undo.Push(previous);dirty=true;await PresentAsync(projectPath,result,false);status.Text="Correction applied. Save to keep it.";
    });
    async Task UndoAsync()
    {
        if(state==null||projectPath==null||undo.Count==0)return;var snapshot=undo.Pop().AsObject();
        state["model"]=snapshot["model"]?.DeepClone();state["crop"]=snapshot["crop"]!.DeepClone();state["model_crop"]=snapshot["model_crop"]!.DeepClone();state["model_crop_stale"]=snapshot["model_crop_stale"]!.DeepClone();
        dirty=true;await PresentAsync(projectPath,state,false);status.Text="Edit undone. Save to keep this version.";
    }
    async Task ApplyCropAsync()
    {
        if(state==null||projectPath==null||busy)return;
        JsonNode? polygon=state["crop"]!["polygon"]?.DeepClone();
        if(viewport.CropDrawing)
        {
            var vertices=viewport.FinishCropDrawing();
            polygon=new JsonArray(vertices.Select(p=>(JsonNode?)new JsonArray((double)p.X,(double)p.Y)).ToArray());
        }
        JsonNode? Height(TextBox box)=>string.IsNullOrWhiteSpace(box.Text)?null:JsonValue.Create(Parse(box.Text!));
        var crop=new JsonObject{["polygon"]=polygon,["z_min"]=Height(cropBottom),["z_max"]=Height(cropTop)};
        await ApplyCropValueAsync(crop,"Crop applied. Save it, then run Detect elements to rebuild candidates inside it.");
    }
    async Task ClearCropAsync()
    {
        if(state==null||projectPath==null||busy)return;viewport.CancelCropDrawing();
        var crop=new JsonObject{["polygon"]=null,["z_min"]=null,["z_max"]=null};
        await ApplyCropValueAsync(crop,"Crop cleared. Save, then run Detect elements to rebuild the full model.");
    }
    async Task ApplyCropValueAsync(JsonObject crop,string message)
    {
        if(state==null||projectPath==null||busy)return;
        if(crop.ToJsonString()==state["crop"]!.ToJsonString()){status.Text="Crop is unchanged.";return;}
        var previous=DraftSnapshot();var request=ModelRequest();request["crop"]=crop.DeepClone();
        var result=await RunAsync("edit_crop",projectPath,request);if(result==null)return;
        undo.Push(previous);dirty=true;await PresentAsync(projectPath,result,false);viewport.FitVisible();status.Text=message;
    }
    async Task RevertAsync(){if(projectPath==null)return;dirty=false;undo.Clear();await LoadAsync(projectPath);}
    async Task MergeWallsAsync(string[]? requested=null)
    {
        if(state==null||projectPath==null||busy)return;var ids=requested??SelectedWallIds();
        if(ids.Length<2){status.Text="Ctrl-click at least two collinear wall rows to merge.";return;}
        var previous=DraftSnapshot();var request=ModelRequest();request["wall_ids"]=new JsonArray(ids.Select(id=>(JsonNode?)JsonValue.Create(id)).ToArray());
        var result=await RunAsync("merge_walls",projectPath,request);if(result==null)return;
        undo.Push(previous);dirty=true;selectedId=ids[0];await PresentAsync(projectPath,result,false);status.Text=$"Merged {ids.Length} wall fragments. Save to keep this version.";
    }
    async Task SplitWallAsync()
    {
        var selection=Selected();if(state==null||projectPath==null||busy||selection==null||selection.Value.Kind!="walls")return;
        var previous=DraftSnapshot();var request=ModelRequest();request["wall_id"]=selection.Value.Node["id"]!.GetValue<string>();request["offset"]=Parse(splitOffset.Text??"");
        var result=await RunAsync("split_wall",projectPath,request);if(result==null)return;
        undo.Push(previous);dirty=true;selectedId=selection.Value.Node["id"]!.GetValue<string>();await PresentAsync(projectPath,result,false);status.Text="Wall split and hosted openings reassigned. Save to keep this version.";
    }
    async Task AddCandidateAsync(string candidateKind)
    {
        var selection=Selected();if(selection==null||state==null||projectPath==null||busy)return;
        var previous=DraftSnapshot();var request=ModelRequest();request["candidate_kind"]=candidateKind;
        request["host_id"]=selection.Value.Node["id"]!.GetValue<string>();
        var result=await RunAsync("add_candidate",projectPath,request);if(result==null)return;
        var before=state["model"]![candidateKind is "door" or "window"?"openings":candidateKind=="stair"?"stairs":candidateKind=="landing"?"landings":"slab_openings"]!.AsArray().Select(n=>n!["id"]!.GetValue<string>()).ToHashSet();
        var collection=candidateKind is "door" or "window"?"openings":candidateKind=="stair"?"stairs":candidateKind=="landing"?"landings":"slab_openings";
        selectedId=result["model"]![collection]!.AsArray().Select(n=>n!["id"]!.GetValue<string>()).FirstOrDefault(id=>!before.Contains(id));
        undo.Push(previous);dirty=true;await PresentAsync(projectPath,result,false);status.Text="Candidate added. Adjust its measured fields, then save or undo.";
    }
    async Task DeleteCandidateAsync()
    {
        var selection=Selected();if(selection==null||state==null||projectPath==null||busy)return;
        var previous=DraftSnapshot();var request=ModelRequest();request["element_id"]=selection.Value.Node["id"]!.GetValue<string>();
        var result=await RunAsync("delete_candidate",projectPath,request);if(result==null)return;
        undo.Push(previous);dirty=true;selectedId=null;await PresentAsync(projectPath,result,false);status.Text="Candidate deleted. Save to keep this version, or undo.";
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
    {var result=await RunAsync("open",path);if(result!=null){dirty=false;undo.Clear();await RunAsync("cleanup",path);await PresentAsync(path,result,true);}}
    async Task ChooseSpecialistFolderAsync()
    {
        var folders=await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions{Title="Choose the supplied specialist ONNX model folder",AllowMultiple=false});
        if(folders.FirstOrDefault()?.TryGetLocalPath() is { } path)specialistModels.Text=path;
    }
    async Task SaveAsync()
    {if(state==null||projectPath==null)return;var result=await RunAsync("save",projectPath,ModelRequest());if(result!=null){dirty=false;await PresentAsync(projectPath,result,false);status.Text="Project saved.";}}
    async Task CheckSpecialistSetupAsync()
    {
        var result=await RunAsync("preflight_recognition",projectPath??"",new JsonObject{
            ["recognition_mode"]="specialist",["specialist_model_directory"]=specialistModels.Text});
        if(result==null)return;
        ShowRecognitionStatus(result);
        status.Text=result["status"]?.GetValue<string>()=="complete"
            ?"Specialist setup passed. Ready to detect elements."
            :"Specialist setup unavailable: "+result["reason"]?.GetValue<string>();
    }
    async Task CopyAsync()
    {
        if(state==null||projectPath==null)return;var destination=await PickProjectAsync("Save project and its data as a new copy");if(destination==null)return;
        var request=ModelRequest();request["destination"]=destination;var result=await RunAsync("save_copy",projectPath,request);if(result!=null){dirty=false;undo.Clear();await PresentAsync(destination,result,false);status.Text="Project copy saved. Keep its assets folder with the project file.";}
    }
    async Task ReconstructAsync()
    {
        if(state==null||projectPath==null||!RequireClean())return;
        if(zUp.IsChecked!=true){status.Text="Confirm Z is up before fitting. A missing CRS can remain explicitly unknown for local review.";return;}
        var request=new JsonObject{["expected_revision"]=state["revision"]!.DeepClone(),["confirm_z_up"]=true,["model_action"]=reconstructionAction.SelectedIndex==1?"add":"replace",["reconstruction_options"]=DetectionOptions(),["recognition_mode"]=recognitionMode.SelectedIndex switch{1=>"specialist",2=>"hybrid",_=>"classical"},["specialist_model_directory"]=string.IsNullOrWhiteSpace(specialistModels.Text)?null:specialistModels.Text,["compare_budgets"]=compareBudgets.IsChecked==true,["settings"]=new JsonObject{["surface_method"]=method.SelectedIndex==1?"region_growing":"contour"}};
        recognitionStatus.Text=recognitionMode.SelectedIndex==0?"Requested: Classical · Awaiting reconstruction":"Provider: PunctoraSpecialistProvider · validating runtime and A-J assets";
        var result=await RunAsync("reconstruct",projectPath,request);if(result!=null){dirty=false;undo.Clear();await RunAsync("cleanup",projectPath);await PresentAsync(projectPath,result,false);var r=result["recognition"];status.Text=r==null?"Candidates ready for review":$"Candidates ready · {r["requested_provider"]?.GetValue<string>()} requested · {r["actual_provider"]?.GetValue<string>()} actual{(r["fallback_reason"]?.GetValue<string>() is { } reason?$" · FALLBACK: {reason}":"")}";}
    }
    async Task AddProjectModelAsync()
    {
        if(state==null||projectPath==null||!RequireClean())return;
        var files=await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions{Title="Add a saved Punctora model",AllowMultiple=false,
            FileTypeFilter=[new FilePickerFileType("Punctora project"){Patterns=["*.punctora"]}]});
        if(files.FirstOrDefault()?.TryGetLocalPath() is not { } source)return;
        var request=new JsonObject{["expected_revision"]=state["revision"]!.DeepClone(),["source_project"]=source,
            ["confirm_shared_source_frame"]=sharedSurveyFrame.IsChecked==true};
        if(!string.IsNullOrWhiteSpace(modelAlignment.Text))
        {
            var parts=modelAlignment.Text.Split(';',StringSplitOptions.TrimEntries);
            if(parts.Length!=4)throw new InvalidDataException("Placement: enter X; Y; Z; yaw degrees from the incoming local frame to this project.");
            var x=Parse(parts[0]);var y=Parse(parts[1]);var z=Parse(parts[2]);var angle=Parse(parts[3])*Math.PI/180;
            var c=Math.Cos(angle);var s=Math.Sin(angle);
            request["alignment_matrix"]=new JsonArray(new JsonArray(c,-s,0d,x),new JsonArray(s,c,0d,y),
                new JsonArray(0d,0d,1d,z),new JsonArray(0d,0d,0d,1d));
        }
        var result=await RunAsync("add_project_model",projectPath,request);
        if(result!=null){dirty=false;undo.Clear();await PresentAsync(projectPath,result,false);status.Text="Models combined. Review alignment and preserved evidence before IFC export.";}
    }
    async Task ExportAsync()
    {
        if(state==null||projectPath==null)return;
        if(state["model"]==null||state["model_crop_stale"]!.GetValue<bool>()){await ReconstructAsync();if(state?["model"]==null||state["model_crop_stale"]!.GetValue<bool>())return;}
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
            specialistModels.Text=Path.Combine(output,"missing-specialist-models");
            await CheckSpecialistSetupAsync();
            if(state!=null||!status.Text!.StartsWith("Specialist setup unavailable:"))
                throw new Exception("Scan-free setup did not report unavailable without a project");
            var path=Path.Combine(output,"walkthrough.punctora");var result=await RunAsync("demo",path,new JsonObject{["two_storeys"]=true});if(result==null)throw new Exception(status.Text);
            await PresentAsync(path,result,true);
            await Task.Delay(150);
            var heightMinimum=viewport.View.Scene.HeightMinimum;var heightMaximum=viewport.View.Scene.HeightMaximum;
            if(!heightLegend.IsVisible||heightLegend.Bounds.Height<100||heightLegend.Bounds.Width<100)
                throw new Exception("Height legend missing from preview");
            using(var legendBitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height),new Vector(96,96)))
            {legendBitmap.Render(this);using var legendStream=File.Create(Path.Combine(output,"height-legend.png"));legendBitmap.Save(legendStream,PngBitmapEncoderOptions.Default);}
            // Logical dimensions reproduce small displays and Windows scaling.
            Width=800;Height=500;await Task.Delay(150);
            if(heightLegend.IsVisible)throw new Exception("Height legend obscures the compact viewport");
            status.Text="Specialist setup unavailable: select the existing A-J model folder. Detection is blocked before opening the scan.";
            ShowRecognitionStatus(new JsonObject{["requested_provider"]="PunctoraSpecialistProvider",
                ["actual_provider"]="unavailable",["active_branches"]=new JsonArray(),
                ["missing_branches"]=new JsonArray("A","B","C","D","E","F","G","H","I","J")});
            await Task.Delay(100);
            var statusPosition=statusBanner.TranslatePoint(new Point(0,0),this)??throw new Exception("Status has no layout position");
            var viewportPosition=viewport.TranslatePoint(new Point(0,0),this)??throw new Exception("Viewport has no layout position");
            if(statusPosition.Y<0||statusPosition.Y+statusBanner.Bounds.Height>viewportPosition.Y+1||viewport.Bounds.Height<50)
                throw new Exception($"Top status obscures the viewport or remains below it: status={statusPosition.Y}/{statusBanner.Bounds.Height}, viewport={viewportPosition.Y}/{viewport.Bounds.Height}");
            var errorColor=statusBanner.Background!.ToString();ShowRecognitionStatus(null);status.Text="Project saved.";
            if(statusBanner.Background!.ToString()==errorColor)throw new Exception("Status state colors did not change");
            ApplyProgress(3,"Stage 1/9: preflight passed · PunctoraSpecialistProvider · runtime CPUExecutionProvider");
            if(!recognitionStatus.Text!.Contains("Runtime: CPUExecutionProvider")||!recognitionStatus.Text.Contains("A-J ready"))
                throw new Exception("Detailed specialist provider status was not displayed");
            ApplyProgress(68,"Stage 5/9: plan/section views · view tile 6 · blocks 199,387 · elapsed 1:02:03");
            if(progress.Value!=68||status.Text!="Stage 5/9: plan/section views · view tile 6 · blocks 199,387 · elapsed 1:02:03")
                throw new Exception("Detailed live specialist stage was not displayed");
            var stageHighlight=statusBanner.Background!.ToString();
            await Task.Delay(500);
            if(statusBanner.Background!.ToString()==stageHighlight)throw new Exception("Stage-change highlight did not settle to the running state");
            statusPosition=statusBanner.TranslatePoint(new Point(0,0),this)??throw new Exception("Detailed status has no layout position");
            viewportPosition=viewport.TranslatePoint(new Point(0,0),this)??throw new Exception("Viewport has no layout position after detailed status");
            if(statusPosition.Y<0||statusPosition.Y+statusBanner.Bounds.Height>viewportPosition.Y+1||viewport.Bounds.Height<50)
                throw new Exception("Detailed status obscures the compact viewport");
            status.Text="Specialist setup unavailable: select the existing A-J model folder. Detection is blocked before opening the scan.";
            ShowRecognitionStatus(new JsonObject{["requested_provider"]="PunctoraSpecialistProvider",
                ["actual_provider"]="unavailable",["active_branches"]=new JsonArray(),
                ["missing_branches"]=new JsonArray("A","B","C","D","E","F","G","H","I","J")});
            File.WriteAllText(Path.Combine(output,"provider-status-verification.json"),new JsonObject{
                ["scan_free_setup"]=true,["top_status_visible"]=true,["state_colors_change"]=true,
                ["detailed_live_stage_visible"]=true,["stage_change_highlight"]=true,["detailed_status_layout"]=true,
                ["requested_actual_and_missing_visible"]=recognitionStatus.Text!.Contains("Missing: A, B, C, D, E, F, G, H, I, J")}.ToJsonString());
            await Task.Delay(100); // Allow the restored status layout to reach the scroll viewport.
            if(leftScroll.Extent.Height<=leftScroll.Viewport.Height)throw new Exception("Short window has no scrollable left panel");
            leftScroll.Offset=new Vector(0,leftScroll.Extent.Height-leftScroll.Viewport.Height);await Task.Delay(100);
            var elementPosition=elements.TranslatePoint(new Point(0,0),leftScroll)??throw new Exception("Element list has no layout position");
            if(leftScroll.Offset.Y<=0||elementPosition.Y<0||elementPosition.Y+elements.Bounds.Height>leftScroll.Bounds.Height+1)throw new Exception("Bottom controls remain unreachable after scrolling");
            var cancelPosition=cancel.TranslatePoint(new Point(0,0),this)??throw new Exception("Toolbar has no layout position");
            if(cancelPosition.X<0||cancelPosition.X+cancel.Bounds.Width>Bounds.Width||cancelPosition.Y+cancel.Bounds.Height>Bounds.Height)throw new Exception("Wrapped toolbar is clipped");
            using(var smallBitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height),new Vector(96,96)))
            {smallBitmap.Render(this);using var smallStream=File.Create(Path.Combine(output,"small-window.png"));smallBitmap.Save(smallStream,PngBitmapEncoderOptions.Default);}
            var smallWindowScrollPassed=true;
            Width=1440;Height=920;leftScroll.Offset=default;await Task.Delay(100);
            // A saved result can fail display while its revision has advanced.
            var oldRevision=state!["revision"]!.ToJsonString();
            var advanced=await RunAsync("save",path,ModelRequest())??throw new Exception(status.Text);
            var broken=advanced.DeepClone().AsObject();
            broken["model"]!["landings"]!.AsArray().Add(new JsonObject{
                ["id"]="broken-preview-only",["storey_id"]=broken["model"]!["storeys"]![0]!["id"]!.DeepClone(),
                ["footprint"]=new JsonArray(new JsonArray(0d,0d),new JsonArray(1d,0d),new JsonArray(2d,0d)),["base"]=0d,["thickness"]=.1});
            await PresentAsync(path,broken,false);
            if(state!["revision"]!.ToJsonString()==oldRevision||!status.Text!.Contains("Model preview failed"))throw new Exception("Preview failure did not adopt saved revision");
            state["model"]=advanced["model"]!.DeepClone();
            await SaveAsync();if(status.Text!="Project saved.")throw new Exception("Retry after preview failure failed: "+status.Text);
            var previewRecoveryPassed=true;
            foreach(var index in new[]{1,0,2}){cloudColor.SelectedIndex=index;viewport.Redraw();await Task.Delay(30);}
            if(heightLegend.IsVisible)throw new Exception("Height legend stayed visible in monochrome mode");
            pointSize.Value=5;if(viewport.View.CloudColor!=CloudColorMode.Monochrome||Math.Abs(viewport.View.PointSize-5)>.001)throw new Exception("Point-cloud display controls did not reach the viewport");
            foreach(var index in new[]{1,2,3,0})
            {
                previewQuality.SelectedIndex=index;
                if(viewport.View.Density.Quality!=(PreviewQuality)index)throw new Exception("Preview quality control did not reach renderer");
            }
            var originalScene=viewport.View.Scene;
            var stressPoints=new float[500_000*7];
            for(var i=0;i<500_000;i++)
            {
                var p=originalScene.PointMinimum+(originalScene.PointMaximum-originalScene.PointMinimum)*new System.Numerics.Vector3(
                    (i%997)/996f,((i*313L)%991)/990f,((i*419L)%983)/982f);
                stressPoints[i*7]=p.X;stressPoints[i*7+1]=p.Y;stressPoints[i*7+2]=p.Z;
                stressPoints[i*7+3]=.5f;stressPoints[i*7+4]=.6f;stressPoints[i*7+5]=.8f;stressPoints[i*7+6]=1;
            }
            viewport.SetScene(new SceneData{Points=stressPoints,Elements=originalScene.Elements,TotalPoints=210_000_000,
                Minimum=originalScene.Minimum,Maximum=originalScene.Maximum,PointMinimum=originalScene.PointMinimum,PointMaximum=originalScene.PointMaximum,
                HeightMinimum=originalScene.HeightMinimum,HeightMaximum=originalScene.HeightMaximum,HeightScaleScope=originalScene.HeightScaleScope});
            await Task.Delay(500);
            var uploadCount=viewport.Diagnostics()["point_buffer_uploads"]!.GetValue<int>();
            var modelBeforeOrbit=state["model"]!.ToJsonString();
            var yawBefore=viewport.View.Camera.Yaw;
            viewport.BeginDiagnosticOrbit();
            for(var i=0;i<90;i++)
            {
                for(var j=0;j<16;j++)viewport.DiagnosticOrbit(new Avalonia.Point(i+j/16d,0));
                if(viewport.PendingFrames>1)throw new Exception("Camera requests queued more than one frame");
                await Task.Delay(16);
            }
            var orbitDiagnostics=viewport.Diagnostics();
            await Task.Delay(500);
            if(viewport.View.Density.Moving||viewport.View.Density.Limit!=500_000)throw new Exception("Adaptive point density did not settle");
            if(viewport.CoalescedMoves<90||Math.Abs(viewport.View.Camera.Yaw-(yawBefore-89.9375f*.008f))>.0001)throw new Exception("Latest camera input was lost or replayed");
            if(viewport.Diagnostics()["point_buffer_uploads"]!.GetValue<int>()!=uploadCount)throw new Exception("Camera movement uploaded the point buffer");
            if(state["model"]!.ToJsonString()!=modelBeforeOrbit)throw new Exception("Preview movement changed IFC source geometry");
            if(!viewport.SoftwareMode&&viewport.ActivePoints!=500_000)throw new Exception("Full 500k resting buffer was not restored");
            var restoredDiagnostics=viewport.Diagnostics();
            viewport.SetScene(originalScene);await Task.Delay(100);
            var bounds=viewport.View.Scene;var insetX=(bounds.PointMaximum.X-bounds.PointMinimum.X)*.1;var insetY=(bounds.PointMaximum.Y-bounds.PointMinimum.Y)*.1;
            var testCrop=new JsonObject{["polygon"]=new JsonArray(
                new JsonArray((double)(bounds.PointMinimum.X+insetX),(double)(bounds.PointMinimum.Y+insetY)),
                new JsonArray((double)(bounds.PointMaximum.X-insetX),(double)(bounds.PointMinimum.Y+insetY)),
                new JsonArray((double)(bounds.PointMaximum.X-insetX),(double)(bounds.PointMaximum.Y-insetY)),
                new JsonArray((double)(bounds.PointMinimum.X+insetX),(double)(bounds.PointMaximum.Y-insetY))),
                ["z_min"]=(double)(bounds.PointMinimum.Z+.05f),["z_max"]=(double)(bounds.PointMaximum.Z-.05f)};
            await ApplyCropValueAsync(testCrop,"verification crop");if(state!["model_crop_stale"]!.GetValue<bool>()!=true||viewport.View.CropPolygon?.Count!=4)throw new Exception("Crop did not reach project and viewport");
            await UndoAsync();var cropUndoRestored=state!["crop"]!["polygon"]==null&&!state["model_crop_stale"]!.GetValue<bool>();if(!cropUndoRestored)throw new Exception("Crop undo failed");
            await ApplyCropValueAsync(testCrop,"verification crop");await SaveAsync();await LoadAsync(path);
            var cropSurvivedReopen=state!["crop"]!["polygon"]?.AsArray().Count==4&&state["model_crop_stale"]!.GetValue<bool>();if(!cropSurvivedReopen)throw new Exception("Crop was lost on reopening");
            if(viewport.View.Scene.HeightMinimum!=heightMinimum||viewport.View.Scene.HeightMaximum!=heightMaximum
                ||orbitDiagnostics["height_minimum_z_m"]!.GetValue<double>()!=heightMinimum
                ||orbitDiagnostics["height_maximum_z_m"]!.GetValue<double>()!=heightMaximum)
                throw new Exception("Project height scale changed while orbiting, cropping or reopening");
            await ClearCropAsync();await SaveAsync();if(state!["model_crop_stale"]!.GetValue<bool>())throw new Exception("Clearing crop did not restore model/crop alignment");
            var sample=state!["model"]!["walls"]![0]!;
            var openingCount=state["model"]!["openings"]!.AsArray().Count;selectedId=sample["id"]!.GetValue<string>();ShowProperties();
            await AddCandidateAsync("door");if(state!["model"]!["openings"]!.AsArray().Count!=openingCount+1||selectedId==null)throw new Exception("Manual opening creation failed");
            await DeleteCandidateAsync();if(state!["model"]!["openings"]!.AsArray().Count!=openingCount)throw new Exception("Manual candidate deletion failed");
            var featureAddDeletePassed=true;
            // Explicit synthetic candidates exercise new preview/edit/save/IFC
            // plumbing independently of the detector's geometry regressions.
            var opening=new JsonObject{["id"]="ui-window",["host_wall_id"]=sample["id"]!.DeepClone(),["kind"]="window",["offset"]=.2,["sill"]=.8,["width"]=.6,["height"]=.8,["provenance"]=new JsonObject{["dimensions"]="user_supplied"},["review_state"]="unreviewed"};
            state["model"]!["openings"]!.AsArray().Add(opening);
            var sx=sample["start"]![0]!.GetValue<double>();var sy=sample["start"]![1]!.GetValue<double>();
            state["model"]!["stairs"]!.AsArray().Add(new JsonObject{["id"]="ui-stair",["storey_id"]=sample["storey_id"]!.DeepClone(),["start"]=new JsonArray(sx,sy),["end"]=new JsonArray(sx+2,sy),["base"]=sample["base"]!.DeepClone(),["width"]=.9,["rise"]=.17,["going"]=.25,["steps"]=8,["tread_thickness"]=.06,["provenance"]=new JsonObject{["treads"]="user_supplied"},["review_state"]="unreviewed"});
            var slab=state["model"]!["slabs"]![0]!;var footprint=slab["footprint"]!.AsArray();
            var slabX=footprint.Select(p=>p![0]!.GetValue<double>()).ToArray();var slabY=footprint.Select(p=>p![1]!.GetValue<double>()).ToArray();
            var openingY=(slabY.Min()+slabY.Max())/2;var openingStart=slabX.Min()+.5;var openingEnd=Math.Min(openingStart+1,slabX.Max()-.5);
            state["model"]!["slab_openings"]!.AsArray().Add(new JsonObject{["id"]="ui-slab-opening",["host_slab_id"]=slab["id"]!.DeepClone(),["start"]=new JsonArray(openingStart,openingY),["end"]=new JsonArray(openingEnd,openingY),["width"]=.6,["source_stair_id"]="ui-stair",["provenance"]=new JsonObject{["footprint"]="user_supplied",["host_slab_id"]="user_supplied"},["review_state"]="unreviewed",["confidence"]=.8,["evidence"]=new JsonObject{["scope"]="Synthetic desktop verification candidate"}});
            await PresentAsync(path,state,false);
            if(!viewport.View.Scene.Elements.Any(e=>e.Kind=="window")||!viewport.View.Scene.Elements.Any(e=>e.Kind=="Stair")||!viewport.View.Scene.Elements.Any(e=>e.Kind=="SlabOpening"))throw new Exception("Feature preview missing");
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
            selectedId="ui-slab-opening";ShowProperties();fields["width"].Text="0.55";review.SelectedItem="reviewed";approveSlabCut.IsChecked=true;await ApplyAsync();
            if(state!["model"]!["slab_openings"]![0]!["ifc_cut_approved"]?.GetValue<bool>()!=true)throw new Exception("Explicit slab cut approval was lost");
            var wallId=sample["id"]!.GetValue<string>();var currentWall=state!["model"]!["walls"]!.AsArray().First(node=>node!["id"]!.GetValue<string>()==wallId)!;
            var dx=currentWall["end"]![0]!.GetValue<double>()-currentWall["start"]![0]!.GetValue<double>();var dy=currentWall["end"]![1]!.GetValue<double>()-currentWall["start"]![1]!.GetValue<double>();
            selectedId=wallId;ShowProperties();splitOffset.Text=(Math.Sqrt(dx*dx+dy*dy)/2).ToString(CultureInfo.InvariantCulture);await SplitWallAsync();
            var splitId=wallId+"-split-2";if(!state!["model"]!["walls"]!.AsArray().Any(node=>node!["id"]!.GetValue<string>()==splitId))throw new Exception("Wall split was not applied");
            await MergeWallsAsync([wallId,splitId]);if(state!["model"]!["walls"]!.AsArray().Any(node=>node!["id"]!.GetValue<string>()==splitId))throw new Exception("Wall merge was not applied");
            await SaveAsync();await LoadAsync(path);if(Math.Abs(state!["model"]!["walls"]![0]!["thickness"]!.GetValue<double>()-.27)>1e-10)throw new Exception("Edit was lost on reopening");
            if(Math.Abs(state!["model"]!["openings"]![0]!["width"]!.GetValue<double>()-.65)>1e-10||Math.Abs(state["model"]!["stairs"]![0]!["going"]!.GetValue<double>()-.28)>1e-10||Math.Abs(state["model"]!["slab_openings"]![0]!["width"]!.GetValue<double>()-.55)>1e-10)throw new Exception("Feature edit lost on reopening");
            selectedId=state["model"]!["walls"]![0]!["id"]!.GetValue<string>();ShowProperties();viewport.View.Selected=selectedId;viewport.Redraw();
            await ExportToAsync(Path.Combine(output,"edited.ifc"));
            await Task.Delay(1800);for(var i=0;i<30;i++){viewport.View.Camera.Yaw+=.008f;viewport.Redraw();await Task.Delay(20);}viewport.CaptureGpu(Path.Combine(output,"viewport-gl.png"));await Task.Delay(700);
            using(var bitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height),new Vector(96,96))){bitmap.Render(this);using var outputStream=File.Create(Path.Combine(output,"desktop.png"));bitmap.Save(outputStream,PngBitmapEncoderOptions.Default);}
            reconstructionScope.SelectedIndex=2;manualLevels.Text="Facade; 0; 3";
            await SaveAsync();await LoadAsync(path);
            if(reconstructionScope.SelectedIndex!=2||!manualLevels.Text!.Contains("Facade"))throw new Exception("Manual detection setup lost on reopening");
            await ReconstructAsync();
            if(state!["model"]!["storeys"]![0]!["name"]!.GetValue<string>()!="Facade"||state["model"]!["slabs"]!.AsArray().Count!=0)
                throw new Exception("Manual exterior bounds did not reach the reconstruction worker");
            File.WriteAllText(Path.Combine(output,"manual-level-verification.json"),new JsonObject{
                ["saved_and_reopened"]=true,["worker_reconstructed_manual_bounds"]=true,
                ["no_invented_slabs"]=true}.ToJsonString());
            var beforeAdd=state["model"]!["walls"]!.AsArray().Count;
            reconstructionAction.SelectedIndex=1;await ReconstructAsync();
            if(state!["model"]!["walls"]!.AsArray().Count!=beforeAdd||state["model"]!["metadata"]!["additive_runs"]?.AsArray().Count!=1)
                throw new Exception("Add to existing model lost geometry or retained duplicate walls");
            await LoadAsync(path);
            var addedProject=await RunAsync("add_project_model",path,new JsonObject{
                ["expected_revision"]=state!["revision"]!.DeepClone(),["source_project"]=path});
            if(addedProject==null||addedProject["model"]!["walls"]!.AsArray().Count!=beforeAdd)
                throw new Exception("Saved-project additive worker failed");
            await PresentAsync(path,addedProject,false);await LoadAsync(path);
            await ExportToAsync(Path.Combine(output,"combined.ifc"));
            File.WriteAllText(Path.Combine(output,"additive-verification.json"),new JsonObject{
                ["worker_additive_reconstruction"]=true,["saved_project_merge"]=true,
                ["save_reopen"]=true,["duplicate_walls_removed"]=true,
                ["ifc_exists"]=File.Exists(Path.Combine(output,"combined.ifc"))}.ToJsonString());
            File.WriteAllText(Path.Combine(output,"ui-verification.json"),new JsonObject{["interactive_preview_passed"]=true,["orbit"]=orbitDiagnostics,["restore"]=restoredDiagnostics,["preview_fixture"]="generated 500k points, simulated 210M source count",["small_window_scroll_passed"]=smallWindowScrollPassed,["preview_failure_recovery_passed"]=previewRecoveryPassed,["edit_survived_reopen"]=true,["wall_topology_edit_survived_reopen"]=true,["crop_undo_restored"]=cropUndoRestored,["crop_survived_reopen"]=cropSurvivedReopen,["feature_add_delete_passed"]=featureAddDeletePassed,["ifc_exists"]=File.Exists(Path.Combine(output,"edited.ifc")),["viewport_backend"]=viewport.Backend,["preview_points"]=viewport.View.Scene.Points.Length/7,["conversion_backend"]="adaptive multicore/GPU",["graphics"]=viewport.Diagnostics()}.ToJsonString());
            if(viewport.Backend.Contains("OpenGL"))
            {
                var a=new System.Numerics.Vector3(-1,-1,0);var b=new System.Numerics.Vector3(1,-1,0);
                var c=new System.Numerics.Vector3(1,1,0);var d=new System.Numerics.Vector3(-1,1,0);
                float[] Mesh(params System.Numerics.Vector3[] p)=>p.SelectMany(v=>new[]{v.X,v.Y,v.Z,.43f,.62f,1f,.4f}).ToArray();
                var first=new SceneElement("skin-a","Wall","s","unreviewed",Mesh(a,b,c,a,c,d));
                var second=new SceneElement("skin-b","Wall","s","unreviewed",Mesh(a,b,d,b,c,d));
                SceneData Skin(List<SceneElement> e)=>new(){Elements=e,Minimum=new(-1,-1,-.01f),Maximum=new(1,1,.01f)};
                viewport.View.Cloud=false;viewport.View.Model=true;viewport.View.Selected=null;viewport.View.Storey=null;
                viewport.View.ZMin=-1;viewport.View.ZMax=1;viewport.View.Opacity=1;viewport.SetCrop(null,null,null);
                viewport.View.Camera.Yaw=0;viewport.View.Camera.Pitch=1.35f;
                viewport.SetScene(Skin([first]),true);await Task.Delay(500);
                viewport.CaptureGpu(Path.Combine(output,"alpha-single.png"));await Task.Delay(500);
                viewport.SetScene(Skin([first,second]),true);await Task.Delay(500);
                viewport.CaptureGpu(Path.Combine(output,"alpha-overlap.png"));await Task.Delay(500);
            }
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
            await Task.Delay(1800);
            var beforePreview=state["model"]?.ToJsonString();
            for(var i=0;i<360;i++){viewport.View.Camera.Yaw+=.004f;viewport.Movement();await Task.Delay(8);}
            var orbit=viewport.Diagnostics();
            await Task.Delay(220);
            var restored=viewport.ActivePoints;
            if(!viewport.SoftwareMode&&restored!=Math.Min(500_000,viewport.View.PreviewPoints.Length/7))throw new Exception("Adaptive preview did not restore its resting density");
            if(state["model"]?.ToJsonString()!=beforePreview)throw new Exception("Camera movement changed the export model");
            viewport.CaptureGpu(Path.Combine(output,"viewport-gl.png"));await Task.Delay(200);
            using(var bitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height),new Vector(96,96)))
            {bitmap.Render(this);using var stream=File.Create(Path.Combine(output,"desktop.png"));bitmap.Save(stream,PngBitmapEncoderOptions.Default);}
            File.WriteAllText(Path.Combine(output,"preview-verification.json"),new JsonObject{["viewport_backend"]=viewport.Backend,["load_project_ms"]=loadMs,["source_points"]=viewport.View.Scene.TotalPoints,["preview_points"]=viewport.View.Scene.Points.Length/7,["warnings_retained"]=state["warnings"]!.DeepClone(),["conversion_backend"]="adaptive multicore/GPU",["graphics"]=viewport.Diagnostics(),["orbit"]=orbit,["restored_points"]=restored,["export_model_unchanged"]=true}.ToJsonString());
            Environment.ExitCode=0;Close();
        }
        catch(Exception e){File.WriteAllText(Path.Combine(output,"ui-error.txt"),e.ToString());Environment.ExitCode=1;Close();}
    }
}

