using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace Punctora.Desktop;

/// <summary>Complete-cloud local Z scale. Camera and crop never change it.</summary>
public sealed class HeightLegend : Border
{
    readonly TextBlock[] values = new TextBlock[4];
    public HeightLegend()
    {
        IsHitTestVisible=false;IsVisible=false;
        HorizontalAlignment=HorizontalAlignment.Right;VerticalAlignment=VerticalAlignment.Top;
        Margin=new Thickness(10);Padding=new Thickness(10);CornerRadius=new CornerRadius(6);
        Background=Brush.Parse("#DD0B1220");
        var panel=new StackPanel{Spacing=8};
        panel.Children.Add(new TextBlock{Text="Local height Z [m]",FontSize=12,Foreground=Brushes.White});
        var grid=new Grid{ColumnDefinitions=new ColumnDefinitions("18,Auto"),Height=132};
        var gradient=new LinearGradientBrush{StartPoint=new RelativePoint(0,1,RelativeUnit.Relative),EndPoint=new RelativePoint(0,0,RelativeUnit.Relative),
            GradientStops=new GradientStops{new GradientStop(Color.FromRgb(20,82,230),0),
                new GradientStop(Color.FromRgb(20,219,199),.33),new GradientStop(Color.FromRgb(255,212,51),.66),
                new GradientStop(Color.FromRgb(242,59,71),1)}};
        grid.Children.Add(new Border{Background=gradient,CornerRadius=new CornerRadius(2)});
        var labels=new Canvas{Width=115};Grid.SetColumn(labels,1);grid.Children.Add(labels);
        for(var i=0;i<4;i++)
        {
            values[i]=new TextBlock{FontSize=11,Foreground=Brushes.White};
            Canvas.SetLeft(values[i],8);Canvas.SetTop(values[i],i switch{0=>0,1=>37,2=>78,_=>116});
            labels.Children.Add(values[i]);
        }
        panel.Children.Add(grid);Child=panel;
    }
    public void SetScale(double minimum,double maximum)
    {
        var fractions=new[]{1.0,.66,.33,0.0};
        var names=new[]{"max","66%","33%","min"};
        for(var i=0;i<4;i++)values[i].Text=$"{(minimum+(maximum-minimum)*fractions[i]).ToString("F2",CultureInfo.InvariantCulture)}  {names[i]}";
    }
}
